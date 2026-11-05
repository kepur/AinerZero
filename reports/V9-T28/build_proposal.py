from pathlib import Path
import hashlib,json
R=Path('/Users/mac/AinerWorkFlow/AinerZero');O=R/'reports/V9-T28'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
old=R/'reports/V9-T6/r2-calib-fixtures/statistical_protocol.json';(O/'lead-protocol-observed.json').write_bytes(old.read_bytes())
manifest=R/'reports/V9-T6/r2-calib-fixtures/manifest.json';m=json.loads(manifest.read_text())
models=[]
for model in ('DA3-SMALL','DA3-BASE'):
 stages=[{'stage':'first_frame','device':'mps','precision':'float32','calls':1,'frames_per_call':1,'worlds':['t6-analytic-room-00'],'views':[0]},
 {'stage':'calibration','device':'mps','precision':'float32','calls':6,'frames_per_call':3,'worlds':sorted({x['world_key'] for x in m['rows']}),'views':[0,1,2]},
 {'stage':'cpu_parity','device':'cpu','precision':'float32','calls':1,'frames_per_call':3,'worlds':['t6-analytic-room-00'],'views':[0,1,2]},
 {'stage':'half_parity','device':'mps','precision':'float16','calls':1,'frames_per_call':3,'worlds':['t6-analytic-room-00'],'views':[0,1,2]},
 {'stage':'frame_order_adverse','device':'mps','precision':'float32','calls':1,'frames_per_call':3,'worlds':['t6-analytic-room-00'],'views':[2,1,0]},
 {'stage':'intrinsics_adverse','device':'mps','precision':'float32','calls':1,'frames_per_call':3,'worlds':['t6-analytic-room-00'],'views':[0,1,2]}]
 stages=[stages[i] for i in (0,1,4,5,2,3)]
 models.append({'variant':model,'stages':stages,'forward_calls':sum(s['calls'] for s in stages),'forward_views':sum(s['calls']*s['frames_per_call'] for s in stages)})
p={'schema':'t6.calibration_proposal.v1','protocol_id':'codex-da3-known-k-anchored-diagnostic-20261026-r1','status':'proposal_unapproved','execution_permitted':False,
 'task_id':'ainerzero.V9.T28','review_task':'ainerzero.V9.T29','author':'codex',
 'supersedes':None,'lead_protocol_observed_sha256':sha(old),'input_manifest_sha256':sha(manifest),'generator_sha256':m['generator_sha256'],
 'profile':{'scene_layer':m['rows'][0]['scene_layer'],'partition':'development','known_intrinsics':True,'extrinsics_supplied_to_teacher':False,'image_width':280,'image_height':210,'process_res':280,'assumption':'known-K synthetic input, not blind intrinsic recovery, metric scale or Blender generalization'},
 'split':{'fit_worlds':sorted({r['world_key'] for r in m['rows'] if r['split']=='fit'}),'holdout_worlds':sorted({r['world_key'] for r in m['rows'] if r['split']=='holdout'}),'unit':'one target view per world per variant','anchor_view':0,'pose_scale_view':2,'scored_view':1,'prohibit_final':True},
 'alignment':{'pose_rotation':'C2W: Rrel_i=R0.T @ Ri; delta=Rrel_gt_1.T @ Rrel_pred_1; residual=LogSO3(delta), radians',
 'pose_translation':'u_i=R0.T@(c_i-c0); b_gt=norm(u_gt_2); s=norm(u_gt_2)/norm(u_pred_2); residual=(s*u_pred_1-u_gt_1)/b_gt',
 'depth_scale':'s_depth=median(D_gt_0/D_pred_0) on frozen valid GT pixels; evaluate s_depth*D_pred_1 vs D_gt_1, no target-view refit',
 'gt_baseline_min_metres':1e-6,'predicted_baseline_min_model_units':1e-12,'pi_branch_refusal_rad':1e-6,
 'gt_used_for_per_world_gauge':[0,2],'gt_used_for_score':[1],'holdout_gt_alignment_disclosed':True,'pool_fit_bias_and_covariance_uses_only_fit_worlds':True,'forbid_centre_only_sim3':True},
 'residual_vector':{'dimension':7,'order':['rotation_x_rad','rotation_y_rad','rotation_z_rad','translation_x_per_anchor_baseline','translation_y_per_anchor_baseline','translation_z_per_anchor_baseline','mean_log_depth_ratio_target'],'depth_component':'mean(log((s_depth*D_pred_1)/D_gt_1))','raw_metrics':['rotation_deg','translation_rel_anchor_baseline','depth_abs_rel','depth_delta1','all_valid_counts','predicted_intrinsics_and_source_known_K']},
 'estimation':{'separate_variants':True,'n_fit_worlds':3,'n_holdout_worlds':3,'mean':'sum(fit residual vectors)/3','sample_covariance':'centered.T@centered/(3-1)','regularization':'none; no inverse or pseudoinverse','full_covariance_rank_ceiling':2,'diagonal_variances':'descriptive only, no presumed independent axes','iid_or_gaussian_verified':False,'population_effective_sample_size':'unknown; at most three fit worlds, worlds are related deterministic fixtures','nees':None,'coverage_95':None,'sensor_noise_registration_allowed':False,'output_status':'limited_aligned_diagnostic_candidate_unregistered'},
 'numerical_parity':{'reference':'world00 known-K MPS-F32 calibration output','cpu_float32':{'atol':0.001,'rtol':0.001},'mps_float16':{'atol':0.01,'rtol':0.01},'fields':['depth','confidence','extrinsics','intrinsics'],'require_same_shapes_and_finite':True,'rule':'all elementwise abs(a-b)<=atol+rtol*abs(reference); report max_abs and failed element counts; no relaxation after results'},
 'negative_controls':{'require_real_forward':True,'frames':'reverse RGB association [2,1,0], keep timestamp/GT score labels [0,1,2]','intrinsics':'multiply only focal_x by1.5 and focal_y by0.75 for all3views; retain positive focal and principal point','same_clean_profile':'all positive calls conditioned on exact frozen K; adverse K uses predeclared changed K','score':'rotation_error_rad + norm(translation_residual3) + depth_abs_rel','required_red':'S_bad >= S_clean + max(0.0001,0.1*S_clean)','boundary_rejection':'record as boundary rejection, not real model-response negative-control proof','unrelated_error':'runtime/MPS/load failure is failure, not expected geometric rejection'},
 'budget':{'cumulative_wall_seconds_max':1200,'single_run_wall_seconds_max':1200,'reserve_before_model_import_seconds':1200,'reserve_before_model_import_views':64,'rss_bytes_max':8*1024**3,'max_resident_models':1,'models':models,'total_planned_forward_calls':sum(s['forward_calls'] for s in models),'total_planned_forward_views':sum(s['forward_views'] for s in models),'unallocated_views':2,'retry_allowed':False,'include_loads_postprocess_and_all_controls_in_wall':True},
 'execution_prerequisites':['T26 and different-author T27 accepted','T29 independent math review and lead immutable SHA registration','central CLI/RunStore/shared lock/resource-power-swap guards before imports','known-K adapter accepts frozen K and records exact preprocessing and source SHA, different-author CPU review before execution','hash-bind all images/GT/manifest/protocol/adapter/upstream/packages/weights and stage-specific adverse associations before run','no final, no source downloads, one resident model, no auto fallback'],
 'failure_policy':['any invalid geometry/missing prediction/zero valid GT/nonfinite depth/rank assumption misuse -> nonzero','any parity/adverse/provenance/guard failure -> nonzero and retain outputs','never substitute synthetic noise, hardcode covariance or coverage, change thresholds, or reset run budget'],
 'claims_forbidden':['registered sensor-noise model','NEES 95 percent calibrated','blind intrinsic recovery','absolute metric pose/depth performance','Blender or real-world validation','capability pass, cache admission, training authorization']}
assert p['budget']['total_planned_forward_views']==62
(O/'proposal.json').write_bytes(canon(p)+b'\n')
(O/'proposal.sha256').write_text(sha(O/'proposal.json')+'  proposal.json\n')
print(json.dumps({'proposal_sha256':sha(O/'proposal.json'),'forward_calls':p['budget']['total_planned_forward_calls'],'views':62,'execution_permitted':False}))
