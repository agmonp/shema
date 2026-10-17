# Third-party notices — Shema commercial edition

Copyright in third-party components stays with their respective authors. Their
licenses take precedence for those components. Shema's commercial license does
not restrict rights granted by the legacy MIT code or third-party licenses.

| Component / author | License | Original source |
|---|---|---|
| Shema public base, Shema contributors (2026) | MIT, copy in licenses/Shema-MIT.txt | https://github.com/agmonp/shema/tree/6db5892 |
| qrcode-generator, Kazuhiko Arase (2009) | MIT | https://github.com/kazuhikoarase/qrcode-generator/blob/master/LICENSE |
| Silero VAD, Silero Team | MIT | https://github.com/snakers4/silero-vad/blob/master/LICENSE |
| ONNX Runtime, Microsoft | MIT | https://github.com/microsoft/onnxruntime/blob/main/LICENSE |
| ZXing / ZXing Android Embedded | Apache-2.0 | https://github.com/journeyapps/zxing-android-embedded |
| AndroidX, Android Open Source Project | Apache-2.0 | https://android.googlesource.com/platform/frameworks/support/ |
| ivrit.ai whisper-large-v3-turbo-ct2 | Apache-2.0 | https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2 |
| 3D-Speaker ERes2NetV2, ModelScope | Apache-2.0 | https://github.com/modelscope/3D-Speaker |
| TitaNet-Large, NVIDIA | CC-BY-4.0 | https://huggingface.co/nvidia/speakerverification_en_titanet_large |
| CED-base, mispeech | Apache-2.0 | https://huggingface.co/mispeech/ced-base |
| larger_clap_general, LAION | Apache-2.0 | https://huggingface.co/laion/larger_clap_general |
| Demucs htdemucs, Meta | MIT | https://github.com/facebookresearch/demucs |
| Gemma 3, Google | Gemma Terms of Use (not MIT/Apache) | https://ai.google.dev/gemma/terms |
| NumPy | BSD-3-Clause | https://github.com/numpy/numpy/blob/main/LICENSE.txt |
| faster-whisper, SYSTRAN / CTranslate2, OpenNMT | MIT | https://github.com/SYSTRAN/faster-whisper / https://github.com/OpenNMT/CTranslate2 |
| sherpa-onnx, k2-fsa | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| PyTorch / torchaudio | BSD-style | https://github.com/pytorch/pytorch / https://github.com/pytorch/audio |
| transformers / huggingface_hub, Hugging Face | Apache-2.0 | https://github.com/huggingface/transformers / https://github.com/huggingface/huggingface_hub |
| librosa / SoundFile | ISC / BSD-3-Clause | https://github.com/librosa/librosa / https://github.com/bastibe/python-soundfile |
| SoundCard (recording on the PC) | BSD-3-Clause | https://github.com/bastibe/SoundCard |
| Ollama | MIT | https://github.com/ollama/ollama |
| FFmpeg (Gyan build; separate executable) | GPL-3.0 build, with other notices | https://www.gyan.dev/ffmpeg/builds/ / https://ffmpeg.org/legal.html |

The NVIDIA and ERes2Net models used are ONNX conversions published by sherpa-onnx:
https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models .
The CED model is the int8 ONNX conversion from sherpa-onnx's audio-tagging-models
release. Credit the original model authors as well as the conversion publisher.
No model authors endorse Shema. No model weights are relicensed by Shema.

Gemma is provided under and subject to the Gemma Terms of Use found at
https://ai.google.dev/gemma/terms . Its prohibited-use policy is at
https://ai.google.dev/gemma/prohibited_use_policy .

Optional Shazam integration is not installed or enabled by this distribution.
Installing it or selecting custom models changes the component inventory.
The wheel distributions installed by pip carry additional transitive licenses;
the final binary distribution requires a matching dependency/SBOM export.
