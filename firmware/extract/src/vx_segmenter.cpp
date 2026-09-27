#include "vx_impl.h"
#include "vx_segmenter.h"
#include <string.h>

// ---------------------------------------------------------------- NoiseFloor

void vx_floor_reset(VxNoiseFloor *nf, const VxConfig *cfg) {
    memset(nf, 0, sizeof(*nf));
    nf->cfg = cfg;
}

static bool startup(const VxNoiseFloor *nf) { return nf->blocks < nf->cfg->floor_startup_blocks; }

// start-up estimate from the sub-blocks so far: (level, spread) of the frames in the "background-like" sub-blocks
static bool robust(const VxNoiseFloor *nf, double *level, double *spread) {
    if (!nf->n_sub) return false;
    double ms[VX_MAX_SUB];
    int k = nf->n_sub;
    for (int i = 0; i < k; i++) ms[i] = (double)nf->sub[i].sum / nf->sub[i].n;
    for (int i = 1; i < k; i++) {   // insertion sort (<= 8 values)
        double v = ms[i];
        int j = i - 1;
        while (j >= 0 && ms[j] > v) {
            ms[j + 1] = ms[j];
            j--;
        }
        ms[j + 1] = v;
    }
    double q = ms[(int)(nf->cfg->floor_startup_pct * (k - 1))] + nf->cfg->floor_startup_keep_db;
    double tot = 0, sq = 0;
    long cnt = 0;
    for (int i = 0; i < k; i++) {
        if ((double)nf->sub[i].sum / nf->sub[i].n <= q) {
            tot += (double)nf->sub[i].sum;
            sq += (double)nf->sub[i].sq;
            cnt += nf->sub[i].n;
        }
    }
    double m = tot / cnt;
    double v = sq / cnt - m * m;
    *level = m;
    *spread = sqrt(v > 0.0 ? v : 0.0);
    return true;
}

double vx_floor_update(VxNoiseFloor *nf, vx_real e_db) {
    const VxConfig *cfg = nf->cfg;
    vx_acc e = (vx_acc)e_db;
    nf->n++;
    nf->block_sum += e;
    nf->block_sq += e * e;
    nf->block_n++;
    if (startup(nf)) {
        nf->sub_sum += e;
        nf->sub_sq += e * e;
        nf->sub_n++;
        if (nf->sub_n >= cfg->floor_startup_sub_frames) {
            if (nf->n_sub < VX_MAX_SUB) {
                nf->sub[nf->n_sub].sum = nf->sub_sum;
                nf->sub[nf->n_sub].sq = nf->sub_sq;
                nf->sub[nf->n_sub].n = nf->sub_n;
                nf->n_sub++;
            }
            nf->sub_sum = nf->sub_sq = 0;
            nf->sub_n = 0;
        }
    }
    if (nf->block_n >= cfg->floor_block_frames) {
        double m = (double)nf->block_sum / nf->block_n;
        double v = (double)nf->block_sq / nf->block_n - m * m;
        double sd = sqrt(v > 0.0 ? v : 0.0);
        double rl, rs;
        if (startup(nf) && robust(nf, &rl, &rs) && m - rl > cfg->floor_startup_trigger_db) {
            m = rl;
            sd = rs;
        }
        if (nf->n_means == cfg->floor_blocks) {   // ring full: drop the oldest
            memmove(nf->means, nf->means + 1, sizeof(double) * (nf->n_means - 1));
            memmove(nf->stds, nf->stds + 1, sizeof(double) * (nf->n_means - 1));
            nf->n_means--;
        }
        nf->means[nf->n_means] = m;
        nf->stds[nf->n_means] = sd;
        nf->n_means++;
        nf->blocks++;
        nf->n_sub = 0;
        nf->sub_sum = nf->sub_sq = 0;
        nf->sub_n = 0;
        nf->block_sum = nf->block_sq = 0;
        nf->block_n = 0;
    }
    return vx_floor_value(nf);
}

double vx_floor_value(const VxNoiseFloor *nf) {
    const VxConfig *cfg = nf->cfg;
    double best;
    if (nf->n_means) {
        best = nf->means[0];
        for (int i = 1; i < nf->n_means; i++)
            if (nf->means[i] < best) best = nf->means[i];
    } else if (nf->block_n) {
        double rl, rs;
        double m = (double)nf->block_sum / nf->block_n;
        best = (robust(nf, &rl, &rs) && m - rl > cfg->floor_startup_trigger_db) ? rl : m;
    } else {
        return cfg->floor_min_db;
    }
    best += cfg->floor_bias_db;
    return best > cfg->floor_min_db ? best : cfg->floor_min_db;
}

double vx_floor_spread(const VxNoiseFloor *nf) {
    if (nf->n_means) {   // lower median of the block stds
        double s[VX_MAX_BLOCKS];
        int k = nf->n_means;
        memcpy(s, nf->stds, sizeof(double) * k);
        for (int i = 1; i < k; i++) {
            double v = s[i];
            int j = i - 1;
            while (j >= 0 && s[j] > v) {
                s[j + 1] = s[j];
                j--;
            }
            s[j + 1] = v;
        }
        return s[(k - 1) / 2];
    }
    if (nf->block_n > 1) {
        double m = (double)nf->block_sum / nf->block_n;
        double v = (double)nf->block_sq / nf->block_n - m * m;
        double sd = sqrt(v > 0.0 ? v : 0.0);
        double rl, rs;
        if (robust(nf, &rl, &rs) && m - rl > nf->cfg->floor_startup_trigger_db) return rs;
        return sd;
    }
    return 0.0;
}

// ---------------------------------------------------------------- SegmentStats

static void seg_begin(VxSegStats *s, const VxFrame *first, double floor_db, double close_over) {
    s->start_index = first->index;
    s->t_start_ms = first->t_ms;
    s->floor_db = floor_db;
    s->close_over_floor_db = close_over;
    s->n = 0;
    s->n_flux = 0;
    s->floor_lin = VX_POW(VXF(10.0), (vx_real)floor_db / VXF(10.0));
    s->w_sum = s->centroid_sum = s->flatness_sum = s->zcr_sum = s->lf_sum = s->hf_sum = s->flux_sum = 0;
    s->cent_sum = s->cent_sq = 0;
    s->cent_n = 0;
    for (int i = 0; i < VX_N_MEL; i++) s->mel8_sum[i] = 0;
    s->p_band_sum = s->p_1k6_sum = s->p_voiced_sum = s->p_hi35_sum = 0;
    s->peak_db = s->peak_centroid = s->peak_flatness = s->peak_zcr = 0;
    s->has_peak = false;
    s->truncated = false;
}

static void seg_add(VxSegStats *s, const VxFrame *f) {
    if (s->n < VX_MAX_SEG) {
        s->e_db[s->n] = f->e_db;
        s->f0[s->n] = f->f0;
        s->clarity[s->n] = f->clarity;
        s->n++;
    }
    if (s->n_flux < VX_ONSET_FRAMES) s->flux[s->n_flux++] = f->flux;
    vx_real w = VX_POW(VXF(10.0), f->e_db / VXF(10.0)) - s->floor_lin;
    if (w < 0) w = 0;
    vx_acc wa = (vx_acc)w;
    s->w_sum += wa;
    s->centroid_sum += wa * f->centroid;
    s->flatness_sum += wa * f->flatness;
    s->zcr_sum += wa * f->zcr;
    s->lf_sum += wa * f->lf_ratio;
    s->hf_sum += wa * f->hf_ratio;
    s->flux_sum += wa * f->flux;
    if ((double)f->e_db > s->floor_db + s->close_over_floor_db && f->centroid > 0) {
        vx_acc lc = (vx_acc)VX_LOG2(f->centroid);
        s->cent_sum += lc;
        s->cent_sq += lc * lc;
        s->cent_n++;
    }
    for (int i = 0; i < VX_N_MEL; i++) s->mel8_sum[i] += f->mel8[i];
    s->p_band_sum += f->p_band;
    s->p_1k6_sum += f->p_1k6;
    s->p_voiced_sum += f->p_voiced;
    s->p_hi35_sum += f->p_hi35;
    if (!s->has_peak || f->e_db > s->peak_db) {
        s->has_peak = true;
        s->peak_db = f->e_db;
        s->peak_centroid = f->centroid;
        s->peak_flatness = f->flatness;
        s->peak_zcr = f->zcr;
    }
}

double vx_seg_wmean(const VxSegStats *s, vx_acc v) { return s->w_sum > 0 ? (double)v / (double)s->w_sum : 0.0; }

// ---------------------------------------------------------------- Segmenter

void vx_seg_reset(VxSegmenter *sg, const VxConfig *cfg) {
    sg->cfg = cfg;
    vx_floor_reset(&sg->floor, cfg);
    sg->floor_db = cfg->floor_min_db;
    sg->open = false;
    sg->n_pending = 0;
    sg->n_recent = 0;
    sg->above = 0;
    sg->cooldown = 0;
    sg->fill_frames = (cfg->win + cfg->hop - 1) / cfg->hop;
}

static void seg_close(VxSegmenter *sg) {
    sg->open = false;
    sg->n_pending = 0;
    sg->n_recent = 0;
    sg->cooldown = (int)nearbyint(sg->cfg->cooldown_ms / sg->cfg->frame_ms());
}

bool vx_seg_push(VxSegmenter *sg, const VxFrame *f) {
    const VxConfig *cfg = sg->cfg;
    double sp = vx_floor_spread(&sg->floor);
    double od = cfg->gate_open_sigma * sp, cd = cfg->gate_close_sigma * sp;
    double open_thr = sg->floor_db + (cfg->gate_open_db > od ? cfg->gate_open_db : od);
    double close_thr = sg->floor_db + (cfg->gate_close_db > cd ? cfg->gate_close_db : cd);
    sg->open_thr_f = (vx_real)open_thr;
    sg->close_thr_f = (vx_real)close_thr;
    double e = (double)f->e_db;
    bool done = false;
    if (!sg->open) {
        if (sg->cooldown > 0) sg->cooldown--;
        bool warm = sg->floor.n >= cfg->warmup_frames;
        sg->above = (e > open_thr && warm && sg->cooldown == 0) ? sg->above + 1 : 0;
        if (sg->above >= cfg->open_frames) {
            // all = recent + [f]; opening = the last open_frames; pre-roll = contiguous earlier frames above close
            int n_all = sg->n_recent + 1;
            int n_open = cfg->open_frames < n_all ? cfg->open_frames : n_all;
            int n_earlier = n_all - n_open;
            int n_pre = 0;
            for (int i = n_earlier - 1; i >= 0; i--) {
                if ((double)sg->recent[i].e_db > close_thr && n_pre < VX_PREROLL) n_pre++;
                else break;
            }
            int first = n_earlier - n_pre;
            const VxFrame *f0 = first < sg->n_recent ? &sg->recent[first] : f;
            seg_begin(&sg->seg, f0, sg->floor_db, close_thr - sg->floor_db);
            for (int i = first; i < n_all; i++) seg_add(&sg->seg, i < sg->n_recent ? &sg->recent[i] : f);
            sg->open = true;
            sg->n_pending = 0;
            sg->above = 0;
            sg->n_recent = 0;
        } else {
            sg->recent[sg->n_recent++] = *f;
            if (sg->n_recent > VX_PREROLL + cfg->open_frames) {
                memmove(sg->recent, sg->recent + 1, sizeof(VxFrame) * (sg->n_recent - 1));
                sg->n_recent--;
            }
        }
    } else {
        if (e > close_thr) {
            for (int i = 0; i < sg->n_pending; i++) seg_add(&sg->seg, &sg->pending[i]);
            sg->n_pending = 0;
            seg_add(&sg->seg, f);
        } else if (sg->n_pending < VX_MAX_HANG) {
            sg->pending[sg->n_pending++] = *f;
        }
        if (sg->n_pending >= cfg->hangover_frames) {
            seg_close(sg);
            done = true;
        } else if (sg->seg.n + sg->n_pending >= cfg->max_segment_frames) {
            sg->seg.truncated = true;
            seg_close(sg);
            done = true;
        }
    }
    if (f->index >= sg->fill_frames) {   // frames whose window still holds start-up zeros say nothing about the room
        double nv = vx_floor_update(&sg->floor, f->e_db);
        if (sg->open && nv > sg->floor_db) {
            double cap = sg->floor_db + cfg->floor_rise_open_db_s * cfg->frame_ms() / 1000.0;
            if (cap < nv) nv = cap;
        }
        sg->floor_db = nv;
    }
    return done;
}

bool vx_seg_flush(VxSegmenter *sg) {
    if (!sg->open) return false;
    seg_close(sg);
    return true;
}
