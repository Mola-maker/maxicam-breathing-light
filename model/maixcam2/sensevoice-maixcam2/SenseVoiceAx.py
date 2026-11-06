import axengine as axe
import numpy as np
import wave
from frontend import WavFrontend
import os
import time
from typing import List, Union, Optional
from tokenizer import SentencepiecesTokenizer
from online_fbank import OnlineFbank
from collections import defaultdict
from typing import Dict
import math

def log_add(*args) -> float:
    """
    Stable log add
    """
    if all(a == -float("inf") for a in args):
        return -float("inf")
    a_max = max(args)
    lsp = math.log(sum(math.exp(a - a_max) for a in args))
    return a_max + lsp

class PrefixScore:
    """For CTC prefix beam search"""

    def __init__(
        self,
        s: float = float("-inf"),
        ns: float = float("-inf"),
        v_s: float = float("-inf"),
        v_ns: float = float("-inf"),
        context_state = None,
        context_score: float = 0.0,
    ):
        self.s = s  # blank_ending_score
        self.ns = ns  # none_blank_ending_score
        self.v_s = v_s  # viterbi blank ending score
        self.v_ns = v_ns  # viterbi none blank ending score
        self.cur_token_prob = float("-inf")  # prob of current token
        self.times_s = []  # times of viterbi blank path
        self.times_ns = []  # times of viterbi none blank path
        self.context_state = context_state
        self.context_score = context_score
        self.has_context = False
        self.token_probs = []  # The maximum probability of each token

    def score(self):
        return log_add(self.s, self.ns)

    def viterbi_score(self):
        return self.v_s if self.v_s > self.v_ns else self.v_ns

    def times(self):
        return self.times_s if self.v_s > self.v_ns else self.times_ns

    def total_score(self):
        return self.score() + self.context_score

class CTCDecoder:
    def __init__(
        self,
        symbol_table: Dict[str, int] = None,
        bpe_model: str = None,
        context_score: float = 6.0,
        blank_id: int = 0,
    ):
        self.context_graph = None
        self.blank_id = blank_id
        self.cur_t = 0
        self.cur_hyps = []
        self.reset()

    def reset(self):
        self.cur_t = 0
        context_root = None if self.context_graph is None else self.context_graph.root
        self.cur_hyps = [(tuple(), PrefixScore(s=0.0, v_s=0.0, context_state=context_root))]

    def copy_context(self, prefix_score, next_score):
        # perfix not changed, copy the context from prefix
        if self.context_graph is not None and not next_score.has_context:
            next_score.context_score = prefix_score.context_score
            next_score.context_state = prefix_score.context_state
            next_score.has_context = True

    def update_context(self, prefix_score, next_score, word_id):
        if self.context_graph is not None and not next_score.has_context:
            context_score, context_state = self.context_graph.forward_one_step(prefix_score.context_state, word_id)
            next_score.context_score = prefix_score.context_score + context_score
            next_score.context_state = context_state
            next_score.has_context = True

    def backoff_context(self):
        if self.context_graph is not None:
            # We should backoff the context score/state when the context is
            # not fully matched at the last time.
            for i, hyp in enumerate(self.cur_hyps):
                score, new_state = self.context_graph.finalize(hyp[1].context_state)
                self.cur_hyps[i][1].context_score = score
                self.cur_hyps[i][1].context_state = new_state

    def ctc_greedy_search(self, ctc_probs: np.ndarray, is_last: bool = False, return_probs: bool = False):
        results = self.ctc_prefix_beam_search(ctc_probs, 1, is_last, return_probs)
        if is_last:
            self.reset()
        if return_probs:
            return {"tokens": results["tokens"][0], "times": results["times"][0], "probs": results["probs"][0]}
        return {"tokens": results["tokens"][0], "times": results["times"][0]}

    def ctc_prefix_beam_search(
        self, ctc_probs: np.ndarray, beam_size: int, is_last: bool = False, return_probs: bool = False
    ):
        for logp in ctc_probs:
            self.cur_t += 1
            # key: prefix, value: PrefixScore
            next_hyps = defaultdict(lambda: PrefixScore())
            # 1. First beam prune: select topk best
            # logp, indices = logp.topk(beam_size)  # (beam_size,)
            if beam_size < len(logp):
                top_indices = np.argpartition(-logp, beam_size - 1)[:beam_size]
                top_logp = logp[top_indices]
                sorted_idx = np.argsort(-top_logp)
                top_indices = top_indices[sorted_idx]
                top_logp = top_logp[sorted_idx]
            else:
                top_indices = np.arange(len(logp))
                top_logp = logp

            for prob, u in zip(logp.tolist(), top_indices.tolist()):
                for prefix, prefix_score in self.cur_hyps:
                    last = prefix[-1] if len(prefix) > 0 else None
                    if u == self.blank_id:  # blank
                        next_score = next_hyps[prefix]
                        next_score.s = log_add(next_score.s, prefix_score.score() + prob)
                        next_score.v_s = prefix_score.viterbi_score() + prob
                        next_score.times_s = prefix_score.times().copy()
                        if return_probs:
                            next_score.token_probs = prefix_score.token_probs.copy()
                        # perfix not changed, copy the context from prefix
                        self.copy_context(prefix_score, next_score)
                    elif u == last:
                        # Update *uu -> *u;
                        next_score1 = next_hyps[prefix]
                        next_score1.ns = log_add(next_score1.ns, prefix_score.ns + prob)
                        if next_score1.v_ns < prefix_score.v_ns + prob:
                            next_score1.v_ns = prefix_score.v_ns + prob
                            if next_score1.cur_token_prob < prob:
                                next_score1.cur_token_prob = prob
                                next_score1.times_ns = prefix_score.times_ns.copy()
                                next_score1.times_ns[-1] = self.cur_t
                        if return_probs:
                            next_score1.token_probs = prefix_score.token_probs.copy()
                            next_score1.token_probs[-1] = max(next_score1.token_probs[-1], prob)
                        self.copy_context(prefix_score, next_score1)
                        # Update *u-u -> *uu, - is for blank
                        n_prefix = prefix + (u,)
                        next_score2 = next_hyps[n_prefix]
                        next_score2.ns = log_add(next_score2.ns, prefix_score.s + prob)
                        if next_score2.v_ns < prefix_score.v_s + prob:
                            next_score2.v_ns = prefix_score.v_s + prob
                            next_score2.cur_token_prob = prob
                            next_score2.times_ns = prefix_score.times_s.copy()
                            next_score2.times_ns.append(self.cur_t)
                        if return_probs:
                            next_score2.token_probs = prefix_score.token_probs.copy()
                            next_score2.token_probs.append(prob)
                        self.update_context(prefix_score, next_score2, u)
                    else:
                        n_prefix = prefix + (u,)
                        next_score = next_hyps[n_prefix]
                        next_score.ns = log_add(next_score.ns, prefix_score.score() + prob)
                        if next_score.v_ns < prefix_score.viterbi_score() + prob:
                            next_score.v_ns = prefix_score.viterbi_score() + prob
                            next_score.cur_token_prob = prob
                            next_score.times_ns = prefix_score.times().copy()
                            next_score.times_ns.append(self.cur_t)
                        if return_probs:
                            next_score.token_probs = prefix_score.token_probs.copy()
                            next_score.token_probs.append(prob)
                        self.update_context(prefix_score, next_score, u)

            # 2. Second beam prune
            next_hyps = sorted(next_hyps.items(), key=lambda x: x[1].total_score(), reverse=True)
            self.cur_hyps = next_hyps[:beam_size]

        cur_hyps = self.cur_hyps
        if is_last:
            self.backoff_context()
            self.reset()

        response = {"tokens": [list(y[0]) for y in cur_hyps], "times": [y[1].times() for y in cur_hyps]}
        if return_probs:
            response["probs"] = [[math.exp(p) for p in y[1].token_probs] for y in cur_hyps]
        return response

def sequence_mask(lengths, maxlen=None, dtype=np.float32):
    # 如果 maxlen 未指定，则取 lengths 中的最大值
    if maxlen is None:
        maxlen = np.max(lengths)

    # 创建一个从 0 到 maxlen-1 的行向量
    row_vector = np.arange(0, maxlen, 1)

    # 将 lengths 转换为列向量
    matrix = np.expand_dims(lengths, axis=-1)

    # 比较生成掩码
    mask = row_vector < matrix
    if mask.shape[-1] < lengths[0]:
        mask = np.concatenate(
            [
                mask,
                np.zeros(
                    (mask.shape[0], lengths[0] - mask.shape[-1]), dtype=np.float32
                ),
            ],
            axis=-1,
        )

    # 返回指定数据类型的掩码
    return mask.astype(dtype)[None, ...]


def unique_consecutive_np(arr):
    """
    找出数组中连续的唯一值，模拟 torch.unique_consecutive(yseq, dim=-1)

    参数:
    arr: 一维numpy数组

    返回:
    unique_values: 去除连续重复值后的数组
    """
    if len(arr) == 0:
        return np.array([])

    if len(arr) == 1:
        return arr.copy()

    # 找出变化的位置
    diff = np.diff(arr)
    change_positions = np.where(diff != 0)[0] + 1

    # 添加起始位置
    start_positions = np.concatenate(([0], change_positions))

    # 获取唯一值（每个连续段的第一个值）
    unique_values = arr[start_positions]

    return unique_values


class SenseVoiceAx:
    """SenseVoice axmodel runner"""

    def __init__(
        self,
        model_path: str,
        max_len: int = 256,
        beam_size: int = 3,
        language: str = "auto",
        hot_words: Optional[List[str]] = None,
        use_itn: bool = True,
        streaming: bool = False,
    ):
        """
        Initialize SenseVoiceAx

        Args:
            model_path: Path of axmodel
            max_len:    Fixed shape of input of axmodel
            beam_size:  Max number of hypos to hold after each decode step
            language:   Support auto, zh(Chinese), en(English), yue(Cantonese), ja(Japanese), ko(Korean)
            hot_words:  Words that may fail to recognize,
                        special words/phrases (aka hotwords) like rare words, personalized information etc.
            use_itn:    Allow Invert Text Normalization if True,
                        ITN converts ASR model output into its written form to improve text readability,
                        For example, the ITN module replaces “one hundred and twenty-three dollars” transcribed by an ASR model with “$123.”
            streaming:  Processes audio in small segments or "chunks" sequentially and outputs text on the fly.
                        Use stream_infer method if streaming is true otherwise infer.

        """
        model_path_root = os.path.dirname(model_path)
        emb_path = os.path.join(model_path_root, "embeddings.npy")
        cmvn_file = os.path.join(model_path_root, "am.mvn")
        bpe_model = os.path.join(
            model_path_root, "chn_jpn_yue_eng_ko_spectok.bpe.model"
        )
        if streaming:
            self.position_encoding = np.load(
                os.path.join(model_path_root, "pe_streaming.npy")
            )
        else:
            self.position_encoding = np.load(
                os.path.join(model_path_root, "pe_nonstream.npy")
            )

        self.streaming = streaming
        self.tokenizer = SentencepiecesTokenizer(bpemodel=bpe_model)

        self.frontend = WavFrontend(
            cmvn_file=cmvn_file,
            fs=16000,
            window="hamming",
            n_mels=80,
            frame_length=25,
            frame_shift=10,
            lfr_m=7,
            lfr_n=6,
        )
        self.model = axe.InferenceSession(model_path)
        self.sample_rate = 16000
        self.blank_id = 0
        self.max_len = max_len
        self.padding = 16
        self.input_size = 560

        self.lid_dict = {
            "auto": 0,
            "zh": 3,
            "en": 4,
            "yue": 7,
            "ja": 11,
            "ko": 12,
            "nospeech": 13,
        }
        self.lid_int_dict = {
            24884: 3,
            24885: 4,
            24888: 7,
            24892: 11,
            24896: 12,
            24992: 13,
        }
        self.textnorm_dict = {"withitn": 14, "woitn": 15}
        self.textnorm_int_dict = {25016: 14, 25017: 15}
        self.emo_dict = {
            "unk": 25009,
            "happy": 25001,
            "sad": 25002,
            "angry": 25003,
            "neutral": 25004,
        }

        self.load_embeddings(emb_path, language, use_itn)
        self.language = language

        # decoder
        if beam_size > 1 and hot_words is not None:
            self.beam_size = beam_size
            symbol_table = {}
            for i in range(self.tokenizer.get_vocab_size()):
                symbol_table[self.tokenizer.decode(i)] = i
            self.decoder = CTCDecoder(hot_words, symbol_table, bpe_model)
        else:
            self.beam_size = 1
            self.decoder = CTCDecoder()

        if streaming:
            self.cur_idx = -1
            self.chunk_size = max_len - self.padding
            self.caches_shape = (max_len, self.input_size)
            self.caches = np.zeros(self.caches_shape, dtype=np.float32)
            self.zeros = np.zeros((1, self.input_size), dtype=np.float32)
            self.neg_mean, self.inv_stddev = (
                self.frontend.cmvn[0, :],
                self.frontend.cmvn[1, :],
            )

            self.fbank = OnlineFbank(window_type="hamming")
            self.masks = sequence_mask(
                np.array([self.max_len], dtype=np.int32),
                maxlen=self.max_len,
                dtype=np.float32,
            )

    @property
    def language_options(self):
        return list(self.lid_dict.keys())

    @property
    def textnorm_options(self):
        return list(self.textnorm_dict.keys())

    def load_embeddings(self, emb_path, language, use_itn):
        self.embeddings = np.load(emb_path, allow_pickle=True).item()
        self.language_query = self.embeddings[language]
        self.textnorm_query = (
            self.embeddings["withitn"] if use_itn else self.embeddings["woitn"]
        )
        self.event_emo_query = self.embeddings["event_emo"]
        self.input_query = np.concatenate(
            (self.textnorm_query, self.language_query, self.event_emo_query), axis=1
        )
        self.query_num = self.input_query.shape[1]

    def choose_language(self, language):
        self.language_query = self.embeddings[language]
        self.input_query = np.concatenate(
            (self.textnorm_query, self.language_query, self.event_emo_query), axis=1
        )
        self.language = language

    def load_data(self, filepath: str) -> np.ndarray:
        try:
            with wave.open(filepath, 'rb') as wf:
                n_frames = wf.getnframes()
                sampwidth = wf.getsampwidth()
                pcm_bytes = wf.readframes(n_frames)
                if sampwidth == 2:
                    np_type = np.int16
                else:
                    np_type = np.int32
                pcm = np.frombuffer(pcm_bytes, dtype=np_type)
        except Exception as e:
            print(f'Load wave file {filepath} error: {e}')
            pcm = np.frombuffer(bytes())
        return pcm

    @staticmethod
    def pad_feats(feats: List[np.ndarray], max_feat_len: int) -> np.ndarray:
        def pad_feat(feat: np.ndarray, cur_len: int) -> np.ndarray:
            pad_width = ((0, max_feat_len - cur_len), (0, 0))
            return np.pad(feat, pad_width, "constant", constant_values=0)

        feat_res = [pad_feat(feat, feat.shape[0]) for feat in feats]
        feats = np.array(feat_res).astype(np.float32)
        return feats

    def preprocess(self, waveform):
        feats, feats_len = [], []
        for wf in [waveform]:
            speech, _ = self.frontend.fbank(wf)
            feat, feat_len = self.frontend.lfr_cmvn(speech)
            feats.append(feat)
            feats_len.append(feat_len)

        feats = self.pad_feats(feats, np.max(feats_len))
        feats_len = np.array(feats_len).astype(np.int32)
        return feats, feats_len

    def postprocess(self, ctc_logits, encoder_out_lens):
        # 提取数据
        x = ctc_logits[0, 4 : encoder_out_lens[0], :]

        # 获取最大值索引
        yseq = np.argmax(x, axis=-1)

        # 去除连续重复元素
        yseq = unique_consecutive_np(yseq)

        # 创建掩码并过滤 blank_id
        mask = yseq != self.blank_id
        token_int = yseq[mask].tolist()

        return token_int

    def infer_waveform(self, waveform: np.ndarray, language="auto"):
        if language != self.language:
            self.choose_language(language)

        # start = time.time()
        feat, feat_len = self.preprocess(waveform)
        # print(f"Preprocess take {time.time() - start}s")

        slice_len = self.max_len - self.query_num
        slice_num = int(np.ceil(feat.shape[1] / slice_len))

        asr_res = []
        for i in range(slice_num):
            if i == 0:
                sub_feat = feat[:, i * slice_len : (i + 1) * slice_len, :]
            else:
                sub_feat = feat[
                    :,
                    i * slice_len - self.padding : (i + 1) * slice_len - self.padding,
                    :,
                ]
            # concat query
            sub_feat = np.concatenate([self.input_query, sub_feat], axis=1)
            real_len = sub_feat.shape[1]
            if real_len < self.max_len:
                sub_feat = np.concatenate(
                    [
                        sub_feat,
                        np.zeros(
                            (1, self.max_len - real_len, sub_feat.shape[-1]),
                            dtype=np.float32,
                        ),
                    ],
                    axis=1,
                )

            masks = sequence_mask(
                np.array([self.max_len], dtype=np.int32),
                maxlen=real_len,
                dtype=np.float32,
            )

            # start = time.time()
            outputs = self.model.run(
                None,
                {
                    "speech": sub_feat,
                    "masks": masks,
                    "position_encoding": self.position_encoding,
                },
            )
            ctc_logits, encoder_out_lens = outputs

            token_int = self.postprocess(ctc_logits, encoder_out_lens)

            if self.tokenizer is not None:
                asr_res.append(self.tokenizer.tokens2text(token_int))
            else:
                asr_res.append(token_int)

        return asr_res

    def infer(
        self, filepath_or_data: Union[np.ndarray, str], language="auto", print_rtf=False
    ):
        assert not self.streaming, "This method is for non-streaming model"

        if isinstance(filepath_or_data, str):
            waveform = self.load_data(filepath_or_data)
            if np.empty(waveform):
                print("Empty waveform")
                return ""
        else:
            waveform = filepath_or_data

        total_time = waveform.shape[-1] / self.sample_rate

        start = time.time()
        asr_res = self.infer_waveform(waveform, language)
        latency = time.time() - start

        if print_rtf:
            rtf = latency / total_time
            print(f"RTF: {rtf}    Latency: {latency}s  Total length: {total_time}s")
        return "".join(asr_res)

    def decode(self, times, tokens):
        times_ms = []
        for step, token in zip(times, tokens):
            if len(self.tokenizer.decode(token).strip()) == 0:
                continue
            times_ms.append(step * 60)
        return times_ms, self.tokenizer.decode(tokens)

    def reset(self):
        self.cur_idx = -1
        self.decoder.reset()
        self.fbank = OnlineFbank(window_type="hamming")
        self.caches = np.zeros(self.caches_shape, dtype=np.float32)

    def get_size(self):
        effective_size = self.cur_idx + 1 - self.padding
        if effective_size <= 0:
            return 0
        return effective_size % self.chunk_size or self.chunk_size

    def stream_infer(self, audio, is_last, language="auto"):
        assert self.streaming, "This method is for streaming model"

        if language != self.language:
            self.choose_language(language)

        self.fbank.accept_waveform(audio, is_last)
        features = self.fbank.get_lfr_frames(
            neg_mean=self.neg_mean, inv_stddev=self.inv_stddev
        )

        if is_last and len(features) == 0:
            features = self.zeros

        for idx, feature in enumerate(features):
            is_last = is_last and idx == features.shape[0] - 1
            self.caches = np.roll(self.caches, -1, axis=0)
            self.caches[-1, :] = feature
            self.cur_idx += 1
            cur_size = self.get_size()
            if cur_size != self.chunk_size and not is_last:
                continue

            speech = self.caches[None, ...]
            outputs = self.model.run(
                None,
                {
                    "speech": speech,
                    "masks": self.masks,
                    "position_encoding": self.position_encoding,
                },
            )
            ctc_logits, encoder_out_lens = outputs
            probs = ctc_logits[0, 4 : encoder_out_lens[0]]
            if cur_size != self.chunk_size:
                probs = probs[self.chunk_size - cur_size :]
            if not is_last:
                probs = probs[: self.chunk_size]
            if self.beam_size > 1:
                res = self.decoder.ctc_prefix_beam_search(
                    probs, beam_size=self.beam_size, is_last=is_last
                )
                times_ms, text = self.decode(res["times"][0], res["tokens"][0])
            else:
                res = self.decoder.ctc_greedy_search(probs, is_last=is_last)
                times_ms, text = self.decode(res["times"], res["tokens"])
            yield {"timestamps": times_ms, "text": text}
