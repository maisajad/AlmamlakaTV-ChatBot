"""multilingual-e5-small through ONNX Runtime, without torch.

The free hosting tier has 512 MB of RAM; torch + sentence-transformers alone need more
than that. This runs the official int8-quantized ONNX export of the same model
(118 MB) with the same recipe sentence-transformers uses for e5: mean pooling over
the attention mask, then L2 normalization.

Tokenization uses the model's SentencePiece file directly. The `tokenizers` library
expands the 250k-token vocabulary to ~250 MB of RAM; SentencePiece needs ~40 MB and
gives identical ids (checked on every chunk plus Arabic, mixed-script and emoji text).
"""

from __future__ import annotations

import os

import numpy as np

MODEL_REPO = "intfloat/multilingual-e5-small"
ONNX_FILE = "onnx/model_qint8_avx512_vnni.onnx"
SPM_FILE = "sentencepiece.bpe.model"
MAX_TOKENS = 512
BATCH_SIZE = 1  # one text at a time keeps activation memory small on a 512 MB instance
# XLM-RoBERTa ids: SentencePiece ids shifted by one, its <unk> (0) mapped to 3,
# and every sequence wrapped in <s> ... </s>.
BOS, PAD, EOS, UNK = 0, 1, 2, 3


class OnnxEmbedder:
    def __init__(self, repo: str = MODEL_REPO, onnx_file: str = ONNX_FILE):
        self.cache_id = f"{repo}/{onnx_file}"  # identifies vectors this model produced
        import onnxruntime as ort
        import sentencepiece as spm
        from huggingface_hub import hf_hub_download

        self.sp = spm.SentencePieceProcessor(model_file=hf_hub_download(repo, SPM_FILE))
        options = ort.SessionOptions()
        options.enable_cpu_mem_arena = False  # don't keep peak activation memory around between calls
        threads = os.environ.get("ONNX_THREADS")
        if threads:
            options.intra_op_num_threads = int(threads)
        self.session = ort.InferenceSession(hf_hub_download(repo, onnx_file), options,
                                            providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}

    def token_ids(self, text: str) -> list[int]:
        pieces = [i + 1 if i else UNK for i in self.sp.encode(text)][:MAX_TOKENS - 2]
        return [BOS] + pieces + [EOS]

    def encode(self, texts: list[str], normalize_embeddings: bool = True, convert_to_numpy: bool = True) -> np.ndarray:
        """Same call shape as SentenceTransformer.encode, so the retriever doesn't care which it gets."""
        out = []
        for start in range(0, len(texts), BATCH_SIZE):
            seqs = [self.token_ids(t) for t in texts[start:start + BATCH_SIZE]]
            width = max(map(len, seqs))
            ids = np.array([s + [PAD] * (width - len(s)) for s in seqs], dtype=np.int64)
            mask = (np.arange(width)[None, :] < np.array([len(s) for s in seqs])[:, None]).astype(np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
            hidden = self.session.run(None, {k: v for k, v in feeds.items() if k in self.input_names})[0]
            vectors = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            if normalize_embeddings:
                vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
            out.append(vectors.astype(np.float32))
        return np.concatenate(out)
