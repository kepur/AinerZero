"""
RLT (Run-Length Tokenization) Frame Dropping - NumPy Reference Implementation

Based on: Choudhury et al., Run-Length Tokenization, arXiv 2411.05222
Equation 10 from ARCHITECTURE_V9 §4: same position blocks merged if
||p_t - p_{t-1}||_inf < tau

Inputs:
  - video_chunks: [T, H/p, W/p, D] array of T video patches/tokens
  - tau: infinity norm threshold for frame dropping

Outputs:
  - retained: [K, D] retained tokens after RLT
  - run_lengths: [K] run length for each retained token (how many original
    frames this token represents)
  - positions: [K, 2] spatial position (h, w) of each retained token in the
    original grid
  - restoration: [T, H/p, W/p, D] restored grid where incorporated blocks
    are filled with the previous token (lossless reconstruction)
  - retention_rate: float = K / (T * ph * pw) (fraction of tokens retained)
"""

import numpy as np


def rlt_frame_dropping(video_chunks, tau):
    """
    Apply RLT frame dropping to a sequence of video chunks.

    For each spatial position (h, w), if the infinity norm between the
    current frame's patch and the previous frame's patch is < tau,
    the current patch is merged into the previous token (run-length
    encoded). Otherwise, it starts a new token.

    The first frame at each position is always kept.

    Args:
        video_chunks (np.ndarray): [T, H/p, W/p, D] tensor of video patches
        tau (float): Infinity norm threshold for frame dropping (tau >= 0)

    Returns:
        retained (np.ndarray): [K, D] retained tokens (kept feature vectors)
        run_lengths (np.ndarray): [K] run length for each retained token
            (number of original frames this token represents)
        positions (np.ndarray): [K, 2] spatial position (h, w) of each token
        restoration (np.ndarray): [T, H/p, W/p, D] lossless restoration grid
            where merged blocks are filled with the previous token
        retention_rate (float): fraction of tokens retained = K / (T * ph * pw)
    """
    # --- Validate inputs ---
    T, ph, pw, D = video_chunks.shape
    assert video_chunks.ndim == 4, f"Expected 4D input, got {video_chunks.ndim}D"
    assert tau >= 0, f"tau must be >= 0, got {tau}"

    # --- Step 1: Compute per-position infinity-norm differences ---
    # diff_max[t, h, w] = ||video_chunks[t+1, h, w, :] - video_chunks[t, h, w, :]||_inf
    # Shape: [T-1, ph, pw]
    prev = video_chunks[:-1]   # [T-1, ph, pw, D]
    curr = video_chunks[1:]    # [T-1, ph, pw, D]

    diffs = np.abs(curr - prev)            # [T-1, ph, pw, D]
    diff_max = np.max(diffs, axis=3)       # [T-1, ph, pw]  (L_inf over the D dim)

    # --- Step 2: Determine which (frame, position) are kept ---
    # Frame 0 at every position is always kept.
    # For t >= 1: keep if diff_max[t-1, h, w] >= tau (i.e. changed enough).
    # We build a mask [T, ph, pw] where True = this (frame, position) is retained.
    keep_mask = np.zeros((T, ph, pw), dtype=bool)
    keep_mask[0] = True  # first frame always kept

    if T > 1:
        # diff_max has shape [T-1, ph, pw]; diff_max[t] corresponds to the
        # change from frame t to t+1. So frame t+1 is kept iff diff_max[t, h, w] >= tau.
        keep_mask[1:] = (diff_max >= tau)  # [T-1, ph, pw] boolean

    # --- Step 3: For each position, compute run lengths of kept tokens ---
    # We process each spatial position independently.
    # For a single position, the kept frame indices (in increasing order)
    # determine the run lengths.

    # Flatten spatial positions: [ph*pw] positions, each has T frame flags
    # keep_mask has shape [T, ph, pw]; we transpose and reshape to [ph*pw, T]
    keep_per_pos = keep_mask.transpose(1, 2, 0).reshape(ph * pw, T)  # [ph*pw, T]

    # Containers for the output arrays
    all_retained = []       # list of [D]-dim feature vectors
    all_run_lengths = []    # list of integers
    all_positions = []      # list of (h, w) tuples

    for pos_idx in range(ph * pw):
        # Map flattened index back to (h, w)
        h = pos_idx // pw
        w = pos_idx % pw

        kept_frames = np.where(keep_per_pos[pos_idx])[0].tolist()  # frame indices kept at this pos

        if not kept_frames:
            continue  # no frames kept at this position (should not happen — frame 0 always kept)

        # Compute run lengths for each kept token at this position.
        # If kept_frames = [i_0, i_1, i_2, ...] with i_0 = 0 always:
        #   run_length[0] = i_1 - i_0   (frames from i_0 to i_1-1 are covered by token 0)
        #   run_length[1] = i_2 - i_1
        #   ...
        #   run_length[-1] = T - i_{-1}  (from last kept frame to end)
        #
        # Verification:
        #   Case: kept = [0, 2] with T=4, meaning frames 0 kept, frame 1 merged, frame 2 kept
        #   - run_length[0] = 2 - 0 = 2  (covers frames 0, 1)
        #   - run_length[1] = 4 - 2 = 2  (covers frames 2, 3)
        #   - K = 2, retention_rate = 2/4 = 0.5 ✓
        #
        #   Case: kept = [0] with T=3, all frames 1,2 merged
        #   - run_length[0] = 3 - 0 = 3
        #   - K = 1, retention_rate = 1/3 ✓

        for k in range(len(kept_frames)):
            if k < len(kept_frames) - 1:
                run_len = kept_frames[k + 1] - kept_frames[k]
            else:
                run_len = T - kept_frames[k]
            all_run_lengths.append(run_len)

        # The retained token at this position is the feature vector at each kept frame.
        # We add each (token, position) pair.
        for tf in kept_frames:
            # The token is video_chunks[tf, h, w, :] where (h, w) = divmod(pos_idx, pw)
            h = pos_idx // pw
            w = pos_idx % pw
            token = video_chunks[tf, h, w, :]  # [D]
            all_retained.append(token.copy())
            all_positions.append((h, w))

    # --- Step 4: Assemble output arrays ---
    K = len(all_retained)  # total number of retained tokens across all positions

    if K == 0:
        # Edge case: shouldn't happen since frame 0 is always kept
        retained = np.zeros((0, D), dtype=video_chunks.dtype)
        run_lengths = np.zeros(0, dtype=int)
        positions = np.zeros((0, 2), dtype=int)
        restoration = np.zeros_like(video_chunks)
        retention_rate = 0.0
    else:
        retained = np.stack(all_retained, axis=0)  # [K, D]
        run_lengths = np.array(all_run_lengths, dtype=int)  # [K]
        positions = np.array(all_positions, dtype=int)  # [K, 2]

        # --- Step 5: Build restoration grid [T, ph, pw, D] ---
        # Restoration: for each (t, h, w), if frame t at (h, w) was kept,
        # restoration[t, h, w, :] = video_chunks[t, h, w, :].
        # If frame t at (h, w) was merged (||p_t - p_{t-1}||_inf < tau),
        # restoration[t, h, w, :] = restoration[t-1, h, w, :] (filled from prev).

        # Start with a copy of the original video chunks
        restoration = video_chunks.copy().astype(video_chunks.dtype)

        # For t = 1 to T-1, where keep_mask[t, h, w] is False (merged),
        # fill from the previous frame.
        # We can do this by propagating the last kept value forward.

        # Propagate kept values forward through merged frames
        # restoration already has the original values; we need to overwrite
        # merged positions with the previous frame's value.

        for t in range(1, T):
            # Find positions where this frame is merged (not kept)
            merged = ~keep_mask[t]  # [ph, pw] - True where merged at frame t
            if not np.any(merged):
                continue
            # For merged positions, copy from previous frame
            restoration[t, merged, :] = restoration[t - 1, merged, :]

        # Compute retention rate
        # K = total retained tokens across all positions
        # Total possible (frame, position) combos = T * ph * pw
        retention_rate = K / (T * ph * pw)

    return retained, run_lengths, positions, restoration, retention_rate