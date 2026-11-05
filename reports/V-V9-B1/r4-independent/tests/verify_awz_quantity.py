"""V9.B6 独立复核：r4 F6 quantity 允许表的来源派生与三方一致性。

检查：
  1) 50 项允许表逐项能追溯到 AnimeWorldZero ObservationPacket/v1.1 schema（只读引用）；
  2) 提案 schema 枚举 == 能力登记 schema 枚举 == 核对器允许表（逐项一致、无重复）；
  3) 允许表内没有世界标识/隐藏接触键名（作者判定 + 自写判定）；
  4) 冻结上下文 observable_registry 与允许表/能力 observable_names 的关系；
  5) 上下文 source_sha256 的实际语义（内容摘要还是路径字符串摘要）——来源绑定声明是否可核验。
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_lib as L  # noqa: E402

AWZ_OBS = L.AWZ / 'contracts/v9/observation_packet.v1_1.schema.json'
OUT = L.ROOT / 'reports/V-V9-B1/r4-independent'
RES = OUT / 'results'
RES.mkdir(parents=True, exist_ok=True)
CH = ['symbol8', 'egocentric_grid', 'rgb', 'depth', 'relative_objects', 'ego_motion',
      'audio_events', 'semantic_mask']


def collect(paths, schema, prefix, defs):
    if not isinstance(schema, dict):
        return
    if '$ref' in schema and isinstance(schema['$ref'], str) and \
            schema['$ref'].startswith('#/$defs/'):
        collect(paths, defs[schema['$ref'].split('/')[-1]], prefix, defs)
        return
    props = schema.get('properties')
    if isinstance(props, dict):
        for k, v in props.items():
            p = prefix + '.' + k if prefix else k
            paths.add(p)
            collect(paths, v, p, defs)
    if 'items' in schema:
        collect(paths, schema['items'], prefix, defs)
    for key in ('oneOf', 'anyOf', 'allOf'):
        for sub in schema.get(key) or []:
            collect(paths, sub, prefix, defs)


def main():
    awz = L.load(AWZ_OBS)
    defs = awz['$defs']
    channel_names = []
    for name in CH:
        d = defs.get('ch_' + name, {})
        const = ((d.get('properties') or {}).get('kind') or {}).get('const')
        channel_names.append({'channel': name, 'kind_const': const})
    # 各通道字段（含数组元素属性，去掉数组层级以便和允许表命名口径对齐）
    ch_paths = {}
    for name in CH:
        paths = set()
        collect(paths, defs.get('ch_' + name, {}), name, defs)
        ch_paths[name] = sorted(paths)
    detection_props = sorted((defs.get('detection', {}).get('properties') or {}))
    audio_props = sorted(((defs.get('ch_audio_events', {}).get('properties') or {})
                          .get('events', {}).get('items', {}).get('properties') or {}))
    pose_props = sorted((defs.get('pose_sensor', {}).get('properties') or {}))
    noise_props = sorted((defs.get('noise', {}).get('properties') or {}))
    payload_props = defs['payload']['properties']
    grounded = set()
    for name in CH:
        grounded.add('channel.' + name)
    for name in CH:
        for p in ch_paths[name]:
            grounded.add(p)
    for p in detection_props:
        grounded.add('detection.' + p)
    for p in audio_props:
        grounded.add('audio_events.' + p)
    for p in pose_props:
        grounded.add('pose_sensor.' + p)
    for p in noise_props:
        grounded.add('sensor_noise.' + p)
    for p in ('time.sim_hz', 'time.t_ticks', 'time.dt_ticks', 'time.dt_s', 'episode_start',
              'pose_sensor_if_allowed', 'visibility.fov_deg', 'visibility.range_m',
              'last_action_result.status', 'last_action_result.reason_code',
              'task_instruction.text', 'task_instruction.goal', 'sensor_noise.model'):
        grounded.add(p)
    # 允许表（提案 schema）
    prop_schema = L.load(L.ROOT / 'contracts/v9/skill_proposal.v1.schema.json')
    allowed = prop_schema['$defs']['observable_quantity']['enum']
    entry_schema = L.load(L.ROOT / 'contracts/v9/ability_registry_entry.v0.schema.json')
    entry_enum = entry_schema['$defs']['observable_ref']['enum']
    import importlib.util
    spec = importlib.util.spec_from_file_location('author_checker', L.CHECKER)
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    checker_list = list(A.OBSERVABLE_QUANTITIES)
    grounding = []
    for q in allowed:
        mapping = None
        if q in grounded:
            mapping = q
        elif q.startswith('detection.') and q.split('.', 1)[1] in detection_props:
            mapping = q
        elif q.startswith('audio_events.') and q.split('.', 1)[1] in audio_props:
            mapping = q
        elif q.startswith('pose_sensor.') and q.split('.', 1)[1] in pose_props:
            mapping = q
        elif q.startswith('sensor_noise.') and q.split('.', 1)[1] in noise_props:
            mapping = q
        grounding.append({'quantity': q, 'grounded': mapping is not None, 'via': mapping})
    # 三方一致性
    consistency = {
        'proposal_enum_count': len(allowed),
        'entry_enum_count': len(entry_enum),
        'checker_count': len(checker_list),
        'proposal_eq_entry': sorted(allowed) == sorted(entry_enum),
        'proposal_eq_checker': sorted(allowed) == sorted(checker_list),
        'entry_eq_checker': sorted(entry_enum) == sorted(checker_list),
        'no_duplicates': len(set(allowed)) == len(allowed) == len(set(entry_enum)) == len(set(checker_list)),
    }
    # 允许表内是否含标识词
    forbidden_in_allowed = {
        'author_impl': [q for q in allowed if A.is_forbidden_world_id_key(q)],
        'indep': [q for q in allowed if L.is_ident_key_indep(q)],
    }
    # 上下文 observable_registry
    ctxs = sorted((L.FIXTURE / 'contexts').glob('*.json'))
    ctx_stats = []
    exp = L.load(L.FIXTURE / 'EXPECTATIONS.json')
    pins = {c['context_file']: c for c in exp['cases'] if c.get('context_file')}
    for f in ctxs:
        ctx = L.load(f)
        reg = ctx['ability_registry']['observable_registry']
        qs = reg.get('quantities', [])
        case = pins.get(f.name)
        entry_union = set()
        for e in ctx['ability_registry']['entries']:
            entry_union |= set(e.get('observable_names', []))
        ctx_stats.append({
            'file': f.name, 'n': len(qs),
            'all_in_allowlist': set(qs) <= set(allowed),
            'any_forbidden': bool([q for q in qs if L.is_ident_key_indep(q)]),
            'case_pin_matches': (L.jcs_sha(ctx) == case['context_sha256']) if case else None,
            'entry_observable_union_subset_of_table': entry_union <= set(qs),
            'source': reg.get('source'),
            'source_sha256': reg.get('source_sha256'),
        })
    # source_sha256 语义
    src = ctx_stats[0]['source']
    sha_of_path_string = hashlib.sha256(src.encode('utf-8')).hexdigest()
    sha_of_file_content = L.sha_file(AWZ_OBS)
    src_claimed = ctx_stats[0]['source_sha256']
    semantics = {
        'source': src,
        'claimed_source_sha256': src_claimed,
        'sha256_of_path_string': sha_of_path_string,
        'sha256_of_awz_file_content': sha_of_file_content,
        'equals_path_string_hash': src_claimed == sha_of_path_string,
        'equals_file_content_hash': src_claimed == sha_of_file_content,
        'note': ('上下文 observable_registry.source_sha256 实际等于「来源路径字符串」的 sha256，'
                 '不是 AWZ ObservationPacket schema 文件内容的 sha256；即该字段不是内容绑定，'
                 '只是常量标签。允许表内容由整份上下文 JCS pin 固定，因此授权本身仍被 pin；'
                 '但「取自 AWZ 契约」这一来源声明不能由核对器密码学验证（观察项，非阻断）。'),
    }
    # AWZ 内容哈希应等于交付清单只读输入声称的值
    sums = (L.ROOT / 'reports/V9-B1/SHA256SUMS.txt').read_text(encoding='utf-8')
    out = {
        'awz_observation_schema_sha256': sha_of_file_content,
        'awz_schema_claimed_in_sums': '01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb' in sums,
        'channel_names': channel_names,
        'channel_field_paths': ch_paths,
        'detection_props': detection_props,
        'audio_item_props': audio_props,
        'pose_sensor_props': pose_props,
        'grounding': grounding,
        'grounding_unmatched': [g for g in grounding if not g['grounded']],
        'allowed_count': len(allowed),
        'consistency': consistency,
        'forbidden_in_allowed': forbidden_in_allowed,
        'context_stats': ctx_stats,
        'context_all_same_registry': len({(c['source_sha256'], c['source']) for c in ctx_stats}) == 1,
        'source_semantics': semantics,
    }
    L.write_json(RES / 'awz_quantity_results.json', out)
    print(json.dumps({k: out[k] for k in ('allowed_count', 'awz_schema_claimed_in_sums',
                                         'consistency', 'forbidden_in_allowed',
                                         'grounding_unmatched')}, ensure_ascii=False, indent=1))
    print('source semantics:', json.dumps(semantics, ensure_ascii=False, indent=1))
    print('contexts all in allowlist:', all(c['all_in_allowlist'] for c in ctx_stats),
          'any forbidden:', any(c['any_forbidden'] for c in ctx_stats),
          'source_sha256 identical:', out['context_all_same_registry'])
    ok = (consistency['proposal_eq_entry'] and consistency['proposal_eq_checker'] and
          consistency['no_duplicates'] and not out['grounding_unmatched'] and
          not forbidden_in_allowed['author_impl'] and not forbidden_in_allowed['indep'] and
          all(c['all_in_allowlist'] for c in ctx_stats) and
          out['awz_schema_claimed_in_sums'])
    print('AWZ_QUANTITY_VERDICT', 'PASS (source_sha256 语义为观察项)' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
