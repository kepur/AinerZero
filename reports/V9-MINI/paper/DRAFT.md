# Write Down the Geometry, Learn the Exceptions: A Preregistered Small-Scale Study of Memory and Planning under Unknown Dynamics

*Working draft r0, 2026-11-19. Internal; not for distribution. Authors, affiliations and repository link to be filled in. See "Notes for the authors" at the end before any submission.*

---

## Abstract

Which structures let a small model that trains in minutes on a laptop both predict and act? We study this question in a controlled navigation setting: procedurally generated 19×19 grid worlds with 3×3 rooms and an egocentric 5×5 view. On each new map, an agent first receives a 400-step exploration prefix and then must reach a goal view that appeared in that prefix. In one world family all transition laws are known to a hand-written prior. In the other, two laws are hidden from it: ice strips that make the agent slide, and one-way teleporters.

We compare agents that differ in what they write down and what they learn:
- six learned-memory agents: a JEPA-style world model with Euclidean or learned quasimetric costs, a latent topological graph, a GRU belief, an SPTM-style topological memory, and a causal Transformer over the full history trained by hindsight goal-conditioned Q-learning;
- agents that keep an explicit metric map and plan on it, whose forward model is either an analytic prior, the prior plus per-map event memory, or the prior plus a gated learned residual.

All claims were registered before the confirmatory runs, with frozen code and thresholds, fresh held-out maps and five training seeds. Every gate was recomputed from the episode logs by a reviewer who did not write the analysis code.

On long goals (shortest path ≥ 20 actions), the metric-map planner with a gated residual trained on self-supervised labels beats the best of the six learned-memory agents by +0.948 [0.921, 0.971] success in the world with known laws and +0.772 [0.724, 0.819] in the world with hidden laws (95% cluster-bootstrap intervals over maps). With hidden laws, the gated residual improves over the analytic prior by +0.171 [0.122, 0.219] and over per-map event memory by +0.112 [0.066, 0.159]. With known laws it does not hurt. Replacing ground-truth training labels with the agent's own localization keeps the gain (+0.174 [0.124, 0.224] over the prior).

Diagnostics suggest that the gap to the learned memories comes mostly from memory structure rather than from weak learning components. The results are limited to this small world and to these implementations.

---

## 1 Introduction

A recurring design question for agents that must both model the world and act in it is how much structure to write down by hand and how much to learn. One line of work learns everything end to end, with latent world models [Ha & Schmidhuber 2018; Hafner et al. 2020; 2023], joint-embedding predictive architectures [LeCun 2022; Assran et al. 2023], or sequence models over long histories [Chen et al. 2021; Parisotto et al. 2020]. Another keeps an explicit spatial representation, such as a metric map [Thrun et al. 2005; Chaplot et al. 2020a] or a topological graph [Savinov et al. 2018; Shah et al. 2021], and learns only parts of the pipeline. A third adds learned residuals to analytic models [Zeng et al. 2020; Johannink et al. 2019; Silver et al. 2018].

We take a deliberately small and controlled view of this question. Our working hypothesis has two parts:
1. Planning should operate on explicit geometry.
2. Learning should be reserved for what the hand-written prior does not know, through a gate that defers to the prior when the learned part has nothing to add.

Two properties of the testbed make this testable:
- **The task requires memory of a new map.** The agent must use a short exploration prefix of a map it has never seen to reach a goal it saw there.
- **One world family hides two laws from the prior.** Learning has something real to contribute, and it can be measured against the prior alone and against per-map memory without learning.

Small scale is a feature here. Every model trains in seconds to half an hour on one laptop, so we can afford what large studies usually cannot:
- a **preregistered confirmatory stage** with frozen code, thresholds and budgets;
- five training seeds and several hundred fresh held-out maps per world;
- **independent recomputation** of every gate from raw episode logs.

**Contributions.**
1. A controlled navigation testbed with known and hidden transition laws, a prefix-then-goal task, and a list of every privileged input each agent uses (§3, §4.5).
2. A hybrid agent: a metric map, an analytic forward prior, per-map event memory, and a gated learned residual. A self-supervised variant takes its training labels from its own localization instead of ground-truth poses (§4.3).
3. A two-stage protocol, unregistered exploration followed by one registered confirmation per milestone, with non-author recomputation (§5).
4. Confirmatory evidence for five claims across two milestones (§6). In this setting, the hybrid beats six learned-memory baselines, the analytic prior, and event memory alone, and survives the removal of ground-truth labels.
5. Diagnostics locating the remaining gaps. On the learned side, the limiting factor is memory structure: a frame-node graph only remembers traversed transitions. On the map side, it is localization at the end of the prefix (§6.3).

We do not claim that explicit maps are better than learned memories in general. We compare specific, small implementations at a fixed data budget (§7).

## 2 Related Work

**Latent world models and planning.**
- Latent dynamics models support planning and policy learning in imagination [Ha & Schmidhuber 2018; Hafner et al. 2020; 2023].
- Joint-embedding predictive architectures predict in representation space rather than pixel space [LeCun 2022; Assran et al. 2023; Bardes et al. 2024]. Recent work regularizes the embedding distribution to avoid collapse [Balestriero & LeCun 2025].
- Our shared world model belongs to this family. We find that an inverse-dynamics term is needed to keep action-relevant information in the latent (§6.4), and that a latent that predicts well does not by itself give a usable planning cost.

**Goal-conditioned values and quasimetrics.**
- Goal-conditioned value functions [Kaelbling 1993; Schaul et al. 2015] and hindsight relabeling [Andrychowicz et al. 2017] are standard for reaching goals from offline data.
- Quasimetric learning enforces the triangle inequality and asymmetry of shortest-path distances [Wang et al. 2023].
- We use a quasimetric cost head on the world-model latent, and hindsight goal-conditioned Q-learning for the Transformer agent.

**Topological and metric memories for navigation.**
- Semi-parametric topological memory (SPTM) builds a graph whose nodes are observations from an exploration sequence, with edges from temporal adjacency and a learned reachability classifier [Savinov et al. 2018]; ViNG applies a similar idea outdoors [Shah et al. 2021].
- Neural metric maps and SLAM-based agents keep an explicit spatial map [Parisotto & Salakhutdinov 2018; Chaplot et al. 2020a; 2020b].
- Memory-augmented agents use recurrent or attention-based memory [Wayne et al. 2018; Parisotto et al. 2020].
- Our latent_topo baseline follows the SPTM recipe. Our latent_attn baseline is a causal Transformer over the full prefix and episode history.

**Residual and hybrid models.**
- Learning residuals on top of analytic models is common in robotics [Zeng et al. 2020; Johannink et al. 2019; Silver et al. 2018].
- Our hybrid differs in two ways. A learned gate decides when the residual is used, so that the model falls back to the prior on inputs unlike its training data. And learned cross-map laws are separated from per-map facts, which go into event memory.

**Preregistration and recomputation.**
- Preregistration separates hypothesis-generating from hypothesis-testing analyses [Nosek et al. 2018].
- We register internally: the frozen document and its hash are in the repository history before the confirmatory runs. We use cluster bootstrap intervals over maps [Davison & Hinkley 1997], because episodes on the same map share a prefix and a start.

## 3 Environment and Task

**Maps.**
- A map is a 19×19 grid of 3×3 rooms, each 5×5 inside, separated by walls with doors.
- Doors come from a random spanning tree plus extra doors with probability 0.35.
- Floor cells carry one of 9 colours by room. Colour is irrelevant to dynamics.
- Maps are generated from integer seeds. Training, exploration and confirmation seed ranges never overlap (§5).

**Observations and actions.**
- The agent observes a 5×5 egocentric view, one-hot over 13 cell types, plus a 4-way compass: 329 dimensions.
- Actions are forward, turn left and turn right.

**Two world families.**
- *m1 (known laws):* forward moves one cell unless blocked by a wall.
- *m2 (hidden laws):* m1 plus two laws the analytic prior does not know.
  - Two rooms each contain a 2-cell-wide ice strip spanning the room. Stepping onto it slides the agent along the strip.
  - Two one-way teleporters move the agent from an entrance cell to an exit at least 8 cells away.
  - Maps whose pose graph is not strongly connected are rejected and regenerated.
  - In random walks, about 1% of forward moves trigger one of these laws.

**Task.**
- For each held-out map, a 400-step persistent random walk (forward with probability 0.7) forms the exploration prefix. Its final pose is the start of every task on that map.
- A goal is a pose visited in the prefix whose view and heading are unique on the map.
- Let d* be the shortest number of actions from the start to the goal cell. A goal is *short* if 4 ≤ d* ≤ 10 and *long* if d* ≥ 20.
- Up to 2 short and 4 long goals are drawn per map. The step budget is 2d* + 20.
- An episode succeeds if the agent reaches the goal cell within the budget. No stop action is needed.
- A goal is *law-relevant* (m2 only) if its shortest path under the analytic prior differs from the true shortest path.
- The agent receives the prefix observations and actions and the goal observation, never coordinates.

## 4 Agents

All agents see the same prefix, start and goal. Table 1 lists them. Hyperparameters are in Appendix A.

**Table 1. Agents.**

| Agent | Memory | Forward model / controller | Learned parts |
|---|---|---|---|
| random | none | uniform random actions | none |
| latent_euclid | single frame | world model; cost = Euclidean distance in latent | encoder, predictor |
| latent_learned | single frame | world model; learned quasimetric cost | + cost head |
| graph_memory | graph of prefix latents | world model; graph shortest path + learned cost | + cost head |
| gru_belief | GRU belief over latents | world model; cost on belief | + GRU, belief cost |
| latent_topo | SPTM-style frame graph | learned reachability + locomotion network | reachability, locomotion |
| latent_attn | full history in a causal Transformer | goal-conditioned Q-values | Transformer, Q head |
| map_analytic | metric map | analytic prior | none |
| map_memory | metric map + per-map event memory | analytic prior | none |
| **map_hybrid** | metric map + event memory | prior + gated residual (true-pose labels) | gate, residual |
| **map_hybrid_self** | metric map + event memory | prior + gated residual (self-supervised labels) | gate, residual |
| map_ungated | metric map + event memory | ungated classifier | classifier |
| map_ungated_aug | metric map + event memory | ungated classifier, near-cell masking augmentation | classifier |
| topo_oracle_ctrl | as latent_topo | local control replaced by true shortest path (privileged) | as latent_topo |
| oracle | true map | true dynamics, shortest path | none |

### 4.1 Shared world model

The first four learned agents share one model trained on random walks from 200 training maps (4 walks × 200 steps each, i.e. 160,000 environment steps per seed). The model has 358,115 parameters and trains for 6,000 steps in under a minute.
- **Encoder and predictor:** an MLP encoder (329 → 256 → 256 → 64) and a residual action-conditioned predictor.
- **Losses:**
  - a latent prediction loss with a 3-step rollout;
  - an inverse-dynamics term that predicts the action from consecutive latents;
  - a sketched isotropic-Gaussian regularizer (SIGReg; weight 0.1, 64 directions) against collapse [Balestriero & LeCun 2025].
- **Planning cost:** kept separate from the prediction space. A quasimetric cost head d(x, y) = ‖s(x) − s(y)‖ + Σ relu(a(x) − a(y)) reads stop-gradient latents. It is trained in the spirit of QRL [Wang et al. 2023]: one-step transitions cost at most 1 and k-step transitions at most k, while distances between random same-map pairs are pushed up.
- **Planning:** latent_euclid and latent_learned search all 27 action sequences of length 3 under the predictor and execute the first action of the cheapest, with ε = 0.05 random actions.
- **graph_memory** builds a graph over the prefix latents, with edges from observed transitions and from learned cost ≤ 3. It plans to a waypoint on the graph and then locally with the learned cost.
- **gru_belief** runs a GRU over (latent, previous action), with a cost between belief and goal trained the same way (3,000 steps). Planning rolls the belief forward through the predicted latents.

### 4.2 Stronger learned-memory baselines

**latent_topo (SPTM-style).** Following Savinov et al. [2018], with its own encoders (266,564 parameters, 6,000 steps).
- **Networks:**
  - a reachability network R(o_i, o_j): positives are frames ≤ 3 steps apart on a training walk, negatives ≥ 25 steps apart;
  - a locomotion network predicts the action that leads from o_t towards o_{t+k}, for 1 ≤ k ≤ 4.
- **Memory graph:** one node per prefix frame. Temporal edges join consecutive frames in both directions, with reverse traversal penalized. Shortcut edges join frames at least 4 steps apart on which R is confident (≥ 0.95).
- **Acting:** the goal is localized by R. At each step the agent localizes within a 4-hop neighbourhood of its previous estimate, falling back to the whole graph. It then follows the farthest reachable waypoint among the next few nodes of the graph shortest path.
- Everything is trained from temporal offsets only, without poses or distances.

**latent_attn (Transformer over the full history).** A causal Transformer (4 layers, width 128, 4 heads, rotary position embeddings [Su et al. 2024], pre-LayerNorm; 1,240,707 parameters) encodes the prefix and the episode so far.
- **Q-head:** a goal-conditioned head cross-attends from the goal observation to the history and outputs a cost-to-go Q(h_t, a, g) = 1 + scale · softplus(·) for each action.
- **Training:** offline, with hindsight relabeling [Andrychowicz et al. 2017] on 200 maps × one 800-step walk, the same number of environment steps as the other agents.
  - Bootstrapped targets are min(1 + min_a′ Q̄(h_{t+1}, a′, g), first-hit time of g later in the walk, 200), where Q̄ is a Polyak-averaged target network (τ = 0.02).
  - The loss is a Huber loss on the scaled error.
  - Windows of 600 steps, 16 sequences × 8 goals per batch, 6,000 steps (about 27 minutes).
- **Acting:** the agent re-encodes the full history each step and acts greedily with ε = 0.05.

### 4.3 Metric-map agents

All map agents share mapping, localization and planning. None of them uses coordinates at test time.
- **Odometry and mapping:** the compass gives heading. A forward model predicts the next pose, and the view is written into the agent's own grid.
- **Surprise and relocalization:** a *surprise* is a mismatch between the predicted view and known map cells. The agent then relocalizes in three stages:
  1. along the heading ray;
  2. failing that, by a unique consistent pose on the whole map;
  3. failing that, it is *lost*: it maps a new fragment while tracking candidate offsets. A fragment is merged back only when one candidate remains and at least 20 overlapping cells all agree.
- **Planning:** breadth-first search on the pose graph under the agent's forward model. The goal is located by matching the goal view against the map. When lost, the agent plans within its fragment or explores its frontier.

The agents differ only in the forward model, which predicts how far one forward action moves given the 6 cells ahead (unknown, wall, ice, teleporter, floor; colour folded):
- **map_analytic:** the prior. Forward moves one cell unless the next cell is a wall; unknown cells are assumed free.
- **map_memory:** the prior plus per-map event memory. It remembers where a forward move from a given pose actually ended, and where a teleporter led.
- **map_hybrid:** a gated residual and event memory.
  - A gate m(x) predicts whether the prior is wrong for input x, and a residual r(x) predicts the outcome. Both are 1-hidden-layer MLPs with 64 units.
  - The residual is trained only on *event* samples, where the true outcome differs from the prior.
  - The prediction is r(x) if m(x) = 1, else the prior.
  - The residual learns cross-map laws (ice slides, teleporters teleport). Event memory stores per-map facts (where this teleporter leads). Teleporters with unknown destination are avoided in planning.
  - Training labels come from ground-truth poses on the training walks; this is a privileged input.
- **map_hybrid_self:** as map_hybrid, but the labels come from the agent's own localization. An analytic-prior map agent walks the same training walks; its label is the predicted displacement when the view agrees, the displacement found on the ray when relocalization succeeds, and "teleported" otherwise. Moves made while lost are discarded.
  - Ground truth is used only to measure label quality: agreement 1.000 in m1 and 0.9993–0.9996 in m2 (per seed, M5 runs).
- **map_ungated / map_ungated_aug:** a single classifier predicts every forward outcome without the prior. The *aug* variant additionally masks near cells during training, so that "unknown cell ahead" inputs are seen in training.

### 4.4 References

**oracle** follows the true shortest path with true dynamics; it checks that every task is feasible. **topo_oracle_ctrl** is latent_topo with its local controller replaced by the true shortest path to the chosen waypoint. It is privileged and report-only: it isolates how much of latent_topo's gap is due to local control.

### 4.5 Privileged inputs

| Privileged input | Agents | Status |
|---|---|---|
| Compass heading | all | given (as in prior work on this task family) |
| View geometry (view cell → world offset) and the analytic "walls block, forward moves one cell" prior | map agents | hand-written known structure; this is what the hybrid writes down |
| Folding cell colours into one floor type | forward models | hand-written canonicalization |
| Forward-model training labels from true poses | map_hybrid, map_ungated* | removed in map_hybrid_self |
| True poses at test time | none | — |
| Goal view unique on the map | task design | not an agent input |

## 5 Protocol

**Two stages.**
- *Exploration* is unregistered and used only to design agents and set thresholds. Its numbers are never reported as evidence.
- Each milestone then gets one *confirmation*. A preregistration document fixes the claims, gates, metric, subset, analysis script, seeds, held-out maps and compute budget, and is frozen together with the code hash. Then the runs execute once.

**Seeds and maps.**
- Training seed s uses training maps from 7,100,000 + 1000·s (200 maps).
- Exploration used held-out maps from 7,900,000 onward.
- M4 used 80 fresh maps per seed from 8,000,000 + 1000·s; M5 used 80 fresh maps per seed from 8,100,000 + 1000·s.
- No two sets overlap. The run script also refuses held-out ranges that overlap the training range.

**Statistics.**
- Every gate compares two agents on the same episodes (paired), on long goals.
- The point estimate is the mean paired difference in success. Episodes of all five runs of a world are pooled.
- Intervals are 95% percentile intervals from a cluster bootstrap: clusters are (training seed × held-out map), 4,000 resamples, and the statistic is the sum of differences over resampled clusters divided by their episode count.
- Clustering by map matters. Episodes on one map share the prefix and start, and per-episode intervals would be about half as wide.

**Recomputation.**
- After each confirmation, a reviewer who did not write the code recomputed every gate from `episodes.json` with their own script.
- They also checked integrity: code hash, library version, seed ranges, episode counts, identical task sequences across agents, oracle success, and run times against the budget.
- Both recomputations agreed with the author's numbers (§6). The reviewers' resampling followed the same random-number order as the author's script, so intervals agree to all digits. This shows a correct reimplementation of the same algorithm, not robustness to a different resampler.
- For M5 we additionally recomputed the main gate with five other random seeds and a multinomial-weights resampler: endpoints moved by at most 0.003.

**Pre-freeze changes.** Thresholds were set after exploration, and the M4 document went through two revisions before freezing (r0 → r1 → r1.1):
- **H4.** It was rewritten from a non-inferiority bound on map_hybrid_self − map_hybrid. After a bug fix, exploration showed that bound was not a test the claim could be expected to pass, because of single-map variance. It became the two-part test in Table 2. The old comparison is reported without a gate.
- **H3.** Its point-estimate threshold returned from +0.10 to the original +0.05.

All versions are in the repository history.

**Budgets.**
- M4: 10 runs, 5,594 s in total against a cap of 9,000 s.
- M5: 10 runs, 22,138 s against a cap of 36,000 s.
- Each run held a machine-wide lock. Before every run the scripts checked the code and preregistration hashes, and for M5 also the MLX version.

## 6 Results

### 6.1 Milestone M4: the hybrid against the prior, event memory and learned memories

M4 tested four claims on 5 seeds × 80 maps per world (m1: 723 long episodes on 186 map clusters; m2: 907 on 231). All gates passed (Table 2).

**Table 2. M4 confirmatory gates** (long-goal success; paired difference [95% cluster-bootstrap interval]).

| Claim | World | Comparison | Gate | Result | Verdict |
|---|---|---|---|---|---|
| H1 | m1 | map_hybrid − best of 4 learned-memory agents | ≥ 0.50, lower > 0 | +0.994 [+0.987, +1.000] | pass |
| H1 | m2 | same | ≥ 0.50, lower > 0 | +0.848 [+0.804, +0.889] | pass |
| H2 | m2 | map_hybrid − map_analytic | ≥ +0.10, lower > 0 | +0.171 [+0.122, +0.219] | pass |
| H2′ | m1 | map_hybrid − map_analytic | lower ≥ −0.02 | 0 [0, 0] | pass |
| H3 | m2 | map_hybrid − map_memory | ≥ +0.05, lower > 0 | +0.112 [+0.066, +0.159] | pass |
| H4 ① | m2 | map_hybrid_self − map_analytic | ≥ +0.08, lower > 0 | +0.174 [+0.124, +0.224] | pass |
| H4 ② | m2 | held-out event accuracy of the forward model, true-pose labels minus self-supervised labels (mean of 5 seeds) | ≤ 0.05 | +0.024 | pass |

- The best learned-memory agent was chosen after the fact, which favours the learned side: latent_euclid with 0.0014 in m1; all four were 0 in m2.
- H4 ② per seed: 0.989 vs 0.966, 0.984 vs 0.969, 0.990 vs 0.953, 0.996 vs 0.973, 0.995 vs 0.973, on 354–475 held-out event samples.

**Table 3. Success rates, M4** (pooled over the five runs of a world).

| Agent | m1 short | m1 long | m2 short | m2 long | m2 law-relevant |
|---|---|---|---|---|---|
| episodes | 800 | 723 | 796 | 907 | 597 |
| oracle | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| map_hybrid_self | 1.000 | 0.996 | 0.996 | 0.851 | 0.819 |
| map_hybrid | 1.000 | 0.996 | 0.996 | 0.848 | 0.814 |
| map_memory | 1.000 | 0.996 | 0.977 | 0.735 | 0.683 |
| map_analytic | 1.000 | 0.996 | 0.977 | 0.677 | 0.610 |
| map_ungated | 1.000 | 0.997 | 0.987 | 0.628 | 0.615 |
| map_ungated_aug | 1.000 | 1.000 | 0.987 | 0.607 | 0.603 |
| latent_euclid | 0.158 | 0.001 | 0.128 | 0 | 0.030 |
| latent_learned | 0.111 | 0 | 0.114 | 0 | 0.012 |
| graph_memory | 0.111 | 0 | 0.114 | 0 | 0.012 |
| gru_belief | 0.096 | 0 | 0.101 | 0 | 0.017 |
| random | 0.102 | 0 | 0.118 | 0 | 0.020 |

**Report-only comparisons (m2, long goals; no gates).**
- map_hybrid_self − map_hybrid: +0.003 [−0.006, +0.013].
- map_hybrid − map_ungated: +0.219 [+0.166, +0.275]; map_hybrid − map_ungated_aug: +0.240 [+0.184, +0.299]. The ungated agents are *worse than the analytic prior*.
  - These comparisons mix two factors: the learned laws, and the prior's optimism about unknown cells, which the ungated classifier lacks. We do not count them as evidence for gating.
- On law-relevant episodes (all lengths), map_hybrid − map_analytic is +0.204 [+0.148, +0.264] on 597 episodes and 196 map clusters.

### 6.2 Milestone M5: stronger learned memories, no ground-truth labels on either side

M4's learned-memory agents were all near zero on long goals, so H1 invites the question of whether stronger, standard learned memories close the gap. M5 re-tests only H1, as H1s, with two changes:
1. The learned side adds latent_topo and latent_attn. The best of the six is again taken after the fact.
2. The map side uses map_hybrid_self. Neither side then uses ground-truth labels, and what differs is the memory structure.

M5 used fresh held-out maps (m1: 762 long episodes on 196 clusters; m2: 936 on 240).

**Table 4. M5 confirmatory gate.**

| Claim | World | Best learned memory (long success) | map_hybrid_self | Difference [95% CI] | Gate | Verdict |
|---|---|---|---|---|---|---|
| H1s | m1 | latent_topo (0.049) | 0.996 | +0.948 [+0.921, +0.971] | ≥ 0.50, lower > 0 | pass |
| H1s | m2 | latent_topo (0.065) | 0.838 | +0.772 [+0.724, +0.819] | ≥ 0.50, lower > 0 | pass |

**Table 5. Success rates, M5** (pooled over the five runs of a world).

| Agent | m1 short | m1 long | m2 short | m2 long | m2 law-relevant |
|---|---|---|---|---|---|
| episodes | 800 | 762 | 800 | 936 | 517 |
| oracle | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| map_hybrid | 1.000 | 0.996 | 0.988 | 0.845 | 0.818 |
| map_hybrid_self | 1.000 | 0.996 | 0.988 | 0.838 | 0.803 |
| map_analytic | 1.000 | 0.996 | 0.975 | 0.656 | 0.532 |
| topo_oracle_ctrl (privileged) | 0.542 | 0.084 | 0.573 | 0.076 | 0.157 |
| latent_topo | 0.446 | 0.049 | 0.474 | 0.065 | 0.122 |
| latent_euclid | 0.168 | 0.005 | 0.122 | 0 | 0.021 |
| latent_attn | 0.126 | 0.004 | 0.114 | 0.002 | 0.023 |
| latent_learned | 0.084 | 0 | 0.109 | 0 | 0.021 |
| graph_memory | 0.080 | 0 | 0.109 | 0 | 0.021 |
| gru_belief | 0.095 | 0 | 0.086 | 0 | 0.010 |
| random | 0.095 | 0 | 0.109 | 0 | 0.021 |

**Report-only comparisons (long goals).**
- map_hybrid_self − latent_attn: m1 +0.992 [+0.982, +0.999]; m2 +0.835 [+0.790, +0.879].
- topo_oracle_ctrl − latent_topo: m1 +0.035 [+0.013, +0.058]; m2 +0.011 [−0.004, +0.026].
- The map side replicates M4 on new maps: m2 long goals 0.845 (map_hybrid), 0.838 (map_hybrid_self), 0.656 (map_analytic).

### 6.3 Where the remaining gaps are (descriptive)

**The learned side is limited by memory structure.**
- latent_topo is clearly not a straw man. On short goals it reaches 0.45–0.47, against 0.08–0.17 for the other learned agents.
- On long goals it stays at 0.05–0.07. Giving it perfect local control (topo_oracle_ctrl) only raises this to about 0.08.
- An exploration-stage bound with ground truth explains why: a memory whose nodes are prefix frames and whose edges are traversed transitions can reach at most a fraction of long goals even with perfect control.
  - The bound uses the exploration held-out maps (40 long goals in m1, 68 in m2). Replaying directed prefix transitions reaches 0.20 in m1 and 0 in m2.
  - Allowing reverse traversal at true cost: 0.45 and 0.10.
  - Reaching 1.00 requires knowing that a move from A north to B implies a move from B south to A, and that seen-but-unvisited cells are traversable. This is exactly the geometry the metric map writes down.
- latent_topo fails long goals with many more whole-graph relocalizations per episode than when it succeeds (m1 6.6 vs 0.5; m2 5.1 vs 0.6). This is not normalized for episode length.

**latent_attn did not learn long-horizon navigation at this data scale.**
- Its short-goal success (0.114–0.126) is at the level of random (0.095–0.109), and long-goal success is at most 0.004.
- In exploration it was equally poor on training maps, so this is not overfitting.
- We read this as a statement about this implementation and data budget (160,000 environment steps), not about Transformer memories in general.

**The map side is limited by localization at the end of the prefix** (M4, m2).
- In about 37% of episodes, the map agents are still lost when the prefix ends. These account for 87% of map_hybrid's long-goal failures.
- Splitting long goals by whether map_hybrid starts lost (399 episodes) or localized (508): map_hybrid succeeds on 0.699 vs 0.965, map_analytic on 0.441 vs 0.862.
- When the agent starts localized, the hybrid is close to the oracle, and its gain over the prior is larger on episodes that start lost.

### 6.4 Exploration-stage observations (not evidence)

The following come from unregistered exploration runs, mostly single-seed, and motivated the design. We report them as observations only.
1. **Inverse dynamics against slow-feature collapse.** Without the inverse-dynamics term, the predictor's one-step error was 0.994 of a "do nothing" baseline; with it, 0.019.
2. **Prediction is not planning.** At long range, the Spearman correlation with true distance was about 0.06 for latent Euclidean distance, 0.05 for the learned cost on single frames and 0.13 for the cost on a GRU belief.
3. **Gating matters out of distribution.** "Unknown cell directly ahead" never occurs in the training inputs. On it, the ungated classifier predicted "blocked" 70% of the time, treating unexplored space as wall, while the gated model deferred to the prior 90% of the time. On in-distribution held-out data the two had similar accuracy (event accuracy 0.989 vs 0.979 at full data).
4. **Gating does not save samples.** At 300 training samples the ungated classifier was more accurate on events (0.79 vs 0.51); the gated model had seen only 3 events.

## 7 Discussion and Limitations

**What the evidence supports.** In this small world, an agent that writes geometry into an explicit metric map and learns only gated corrections for unknown laws:
- reaches long goals far more often than six learned-memory agents trained on the same data;
- improves over the analytic prior and over per-map event memory when laws are hidden, without hurting when laws are known;
- keeps these properties when its training labels come from its own localization.

**What it does not support.**
- That explicit maps beat learned memories in general.
- That latent world models or Transformer memories cannot learn this task.
- That the full architecture this study was designed to probe is "correct".

**Limitations.**
1. **Scale and realism.** The world is small (19×19, 3×3 rooms, 5×5 view), fully discrete and noise-free, with two hidden laws. The task distribution is defined by one generator.
2. **Baselines.** All learned-memory agents are our own small implementations at a fixed budget of 160,000 environment steps per seed. SPTM-style and Transformer agents follow published recipes in spirit but not in code or scale. A Dreamer-style recurrent state-space model is not included; gru_belief is a small relative.
3. **Asymmetric inductive bias.** The map agents are given view geometry, the analytic prior and colour folding (§4.5). H1/H1s therefore compare "geometry written down" against "geometry learned from 160,000 steps". This asymmetry is the claim under test, but it should not be read as a like-for-like comparison of learning algorithms.
4. **Compass.** All agents receive the true heading.
5. **Statistics.** Five training seeds per world. Intervals are over maps from one generator. The best learned agent is selected post hoc, which favours the learned side.
6. **Independence of recomputation.** The recomputations reimplemented the same estimator with the same random-number order (§5).

**Next steps.**
- Larger maps and more hidden laws, to test whether the conclusions survive scale.
- A Dreamer-style recurrent world model as an additional baseline.
- Better localization at the end of the prefix, the dominant remaining failure of the map agents.

## 8 Reproducibility

- **Software:** Python 3.12 with NumPy and MLX 0.32.2 [Hannun et al. 2023]; nothing else.
- **Hardware:** one Apple M2 Max laptop.
- **One run** trains every agent, evaluates every task and writes `result.json` (code hash, git head, MLX version, timings) and `episodes.json` (every episode). Command:

  `python -m ainerzero.v9.mini.run --preset medium --world {m1|m2} --seed s --eval-seed0 <seed> --eval-layouts 80`

- **Run times:**
  - M4: about 9 minutes per run; 5,594 s for all ten runs.
  - M5: about 37 minutes per run, of which about 27 minutes is latent_attn training; 22,138 s for all ten.
- **Repository contents:**
  - the frozen preregistrations and their hashes;
  - judge scripts, registered outputs and recomputations;
  - acceptance records.
- **Table sources:**
  - Tables 2 and 4 are copied from the registered result reports.
  - Tables 3 and 5 are generated by `reports/V9-MINI/paper/make_tables.py`. That script pools episodes over runs; the M4 report used per-seed means, which differ in the third decimal.

## References (to be verified before submission)

- Andrychowicz, M. et al. Hindsight experience replay. NeurIPS 2017.
- Assran, M. et al. Self-supervised learning from images with a joint-embedding predictive architecture. CVPR 2023.
- Balestriero, R. & LeCun, Y. LeJEPA: provable and scalable self-supervised learning without the heuristics. arXiv 2025. *(verify title, year and that SIGReg is introduced there)*
- Bardes, A. et al. Revisiting feature prediction for learning visual representations from video (V-JEPA). TMLR 2024. *(verify venue)*
- Chaplot, D. S. et al. Learning to explore using Active Neural SLAM. ICLR 2020a.
- Chaplot, D. S. et al. Neural topological SLAM for visual navigation. CVPR 2020b.
- Chen, L. et al. Decision Transformer: reinforcement learning via sequence modeling. NeurIPS 2021.
- Davison, A. C. & Hinkley, D. V. Bootstrap Methods and Their Application. Cambridge University Press, 1997.
- Ha, D. & Schmidhuber, J. World models. arXiv 2018 / NeurIPS 2018.
- Hafner, D. et al. Dream to control: learning behaviors by latent imagination. ICLR 2020.
- Hafner, D. et al. Mastering diverse domains through world models (DreamerV3). arXiv 2023. *(cite journal version if available)*
- Hannun, A. et al. MLX: efficient and flexible machine learning on Apple silicon. GitHub, 2023.
- Johannink, T. et al. Residual reinforcement learning for robot control. ICRA 2019.
- Kaelbling, L. P. Learning to achieve goals. IJCAI 1993.
- LeCun, Y. A path towards autonomous machine intelligence. OpenReview, 2022.
- Nosek, B. A. et al. The preregistration revolution. PNAS 2018.
- Parisotto, E. & Salakhutdinov, R. Neural Map: structured memory for deep reinforcement learning. ICLR 2018.
- Parisotto, E. et al. Stabilizing transformers for reinforcement learning. ICML 2020.
- Savinov, N., Dosovitskiy, A. & Koltun, V. Semi-parametric topological memory for navigation. ICLR 2018.
- Schaul, T. et al. Universal value function approximators. ICML 2015.
- Shah, D. et al. ViNG: learning open-world navigation with visual goals. ICRA 2021.
- Silver, T. et al. Residual policy learning. arXiv 2018.
- Su, J. et al. RoFormer: enhanced transformer with rotary position embedding. Neurocomputing 2024.
- Thrun, S., Burgard, W. & Fox, D. Probabilistic Robotics. MIT Press, 2005.
- Wang, T. et al. Optimal goal-reaching reinforcement learning via quasimetric learning. ICML 2023.
- Wayne, G. et al. Unsupervised predictive memory in a goal-directed agent (MERLIN). arXiv 2018.
- Zeng, A. et al. TossingBot: learning to throw arbitrary objects with residual physics. IEEE T-RO 2020 (RSS 2019).

## Appendix A. Hyperparameters

| Component | Setting |
|---|---|
| Training data (per seed) | 200 maps × 4 walks × 200 steps (latent_attn: 200 maps × 1 walk × 800 steps) |
| World model | encoder 329→256→256→64; residual predictor; inverse-dynamics head; 3-step rollout; SIGReg weight 0.1, 64 directions; 6,000 steps, batch 256, lr 3e-4; 358,115 parameters |
| Cost head | quasimetric, symmetric part 64-d, asymmetric part 32-d; stop-gradient input |
| Latent planners | exhaustive search over 3-step action sequences (27), ε = 0.05 |
| gru_belief | 3,000 steps |
| latent_topo | embedding 64, hidden 256; positives ≤ 3 steps, negatives ≥ 25 steps; locomotion horizon ≤ 4; shortcut threshold 0.95; localization threshold 0.5 within 4 hops; 6,000 steps, batch 256; 266,564 parameters |
| latent_attn | 4 layers, width 128, 4 heads, RoPE, pre-LN; window 600; 16 sequences × 8 goals; τ = 0.02; initial cost 100; cap 200; 6,000 steps, lr 3e-4; ε = 0.05; 1,240,707 parameters |
| Forward models | input: 6 cells ahead, 5 classes; gate and residual: MLP with 64 hidden units, 600 steps; residual trained on event samples only; near-cell masking 0.15 for map_ungated_aug |
| Map merging | ≥ 20 overlapping cells, all consistent |
| Task | prefix 400 steps; short 4 ≤ d* ≤ 10, long d* ≥ 20; ≤ 2 short and ≤ 4 long goals per map; budget 2d* + 20 |

---

## Notes for the authors (remove before submission)

1. **References.** All references were written from memory and must be checked: titles, years, venues, and in particular whether SIGReg is due to the cited LeJEPA paper.
2. **Disclosure.** The experiments, analysis code, preregistrations and this draft were produced with AI coding agents. The non-author recomputations were done by a different AI agent from the one that wrote the code. Check the target venue's policy on AI assistance and describe these roles accurately; §5's "reviewer who did not write the code" should not be read as a human reviewer.
3. **"Preregistered".** Registration is internal (frozen documents with hashes in the repository history), not on a public registry. Either keep the wording "registered internally" as in §2 and §5, or register future milestones publicly.
4. **Figures to make.** An example map with prefix, start and goal; the agent pipeline; a bar chart of long-goal success per agent and world (Tables 3 and 5); and the localization split of §6.3.
5. **Biggest reviewer risk.** Scale and realism (§7, limitation 1). The planned next milestone, a larger or harder world, is meant to address it.
6. **External steps** (arXiv, an mlx-examples pull request) need the project owner's approval.
