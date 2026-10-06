"""Transcribe WAV files with faster-whisper large-v3 on the GPU.

usage: C:\\claude\\utils\\whisper-venv\\Scripts\\python.exe tools/transcribe.py <out.tsv> <wav...>
"""
import os, sys, glob, site

for sp in site.getsitepackages():                      # CUDA DLLs from the nvidia-* wheels
    for sub in ('nvidia/cublas/bin', 'nvidia/cudnn/bin'):
        p = os.path.join(sp, sub)
        if os.path.isdir(p):
            os.add_dll_directory(p)
            os.environ['PATH'] = p + os.pathsep + os.environ['PATH']

import wave
import numpy as np
from faster_whisper import WhisperModel


def load16k(path):
    """mono 16-bit WAV -> float32 at 16 kHz (no PyAV)"""
    with wave.open(path) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), '<i2').astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    t = np.arange(0, len(x) / sr, 1 / 16000)
    return np.interp(t, np.arange(len(x)) / sr, x).astype(np.float32)


def main():
    out, *pats = sys.argv[1:]
    files = sorted({f for p in pats for f in glob.glob(p)})
    model = WhisperModel('large-v3', device='cuda', compute_type='float16')
    with open(out, 'w', encoding='utf-8') as o:
        o.write('파일\t시작\t끝\t영어\t확률\n')
        for f in files:
            segs, info = model.transcribe(load16k(f), language='en', beam_size=5, vad_filter=False,
                                          condition_on_previous_text=False)
            segs = list(segs)
            if not segs:
                o.write(f'{os.path.basename(f)}\t\t\t(인식 없음)\t\n')
            for s in segs:
                o.write(f'{os.path.basename(f)}\t{s.start:.2f}\t{s.end:.2f}\t{s.text.strip()}\t{s.avg_logprob:.2f}\n')
            print(os.path.basename(f), '|', ' / '.join(s.text.strip() for s in segs))


if __name__ == '__main__':
    main()
