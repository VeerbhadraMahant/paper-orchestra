# Corpus candidates (pool, not the final draw)

Collected 2026-11-22. Titles, first authors and years come from the arXiv listing/API; licenses from arXiv abs pages; reference counts and venues from the Semantic Scholar batch API. "TeX source" means `arxiv.org/format/<id>` returned HTTP 200 (not yet downloaded). Spot-checked against the arXiv API by hand: 2402.06196, 2208.04309, 2206.09328, 2502.05151, 2306.13549 (title, first author, year all match; licenses of 2402.06196 and 2208.04309 confirmed CC BY 4.0). Everything else is unverified until the draw.

| arXiv id | Title | First author | Year | Subfield | License | Refs (S2) |
|---|---|---|---|---|---|---|
| 2402.06196 | Large Language Models: A Survey | Shervin Minaee | 2024 | LLM | CC BY 4.0 | 241 |
| 2303.18223 | A Survey of Large Language Models | Wayne Xin Zhao | 2023 | LLM | arXiv non-exclusive | 461 |
| 2212.09597 | Reasoning with Language Model Prompting: A Survey | Shuofei Qiao | 2022 | LLM | arXiv non-exclusive | 218 |
| 2412.10400 | Reinforcement Learning Enhanced LLMs: A Survey | Shuhe Wang | 2024 | LLM | CC BY-NC-SA 4.0 | 110 |
| 2208.04309 | 3D Vision with Transformers: A Survey | Jean Lahoud | 2022 | CV | CC BY 4.0 | 185 |
| 2206.09328 | A Survey on Model-based Reinforcement Learning | Fan-Ming Luo | 2022 | RL | CC BY 4.0 | 191 |
| 2209.00796 | Diffusion Models: A Comprehensive Survey of Methods and Applications | Ling Yang | 2022 | Generative | arXiv non-exclusive | 394 |
| 2409.19365 | Conditional Image Synthesis with Diffusion Models: A Survey | Zheyuan Zhan | 2024 | Generative | CC BY 4.0 | 257 |
| 2507.16869 | Controllable Video Generation: A Survey | Yue Ma | 2025 | Generative | arXiv non-exclusive | 305 |
| 2203.15935 | Graph Neural Networks in IoT: A Survey | Guimin Dong | 2022 | GNN | CC BY-NC-ND 4.0 | 344 |
| 2202.07082 | Graph Neural Networks for Graphs with Heterophily: A Survey | Xin Zheng | 2022 | GNN | arXiv non-exclusive | 169 |
| 2204.08570 | A Comprehensive Survey on Trustworthy Graph Neural Networks: Privacy, Robustness, Fairness, and Explainability | Enyan Dai | 2022 | GNN | arXiv non-exclusive | 258 |
| 2302.10637 | A Survey of Trustworthy Federated Learning with Perspectives on Security, Robustness, and Privacy | Yifei Zhang | 2023 | Privacy/security | arXiv non-exclusive | 275 |
| 2307.15838 | Holistic Survey of Privacy and Fairness in Machine Learning | Sina Shaham | 2023 | Privacy/fairness | CC BY 4.0 | unverified |
| 2402.09748 | Model Compression and Efficient Inference for Large Language Models: A Survey | Wenxiao Wang | 2024 | Efficient ML | arXiv non-exclusive | 368 |
| 2401.00625 | Beyond Efficiency: A Systematic Survey of Resource-Efficient Large Language Models | Guangji Bai | 2024 | Efficient ML | arXiv non-exclusive | 245 |
| 2405.00314 | Model Quantization and Hardware Acceleration for Vision Transformers: A Comprehensive Survey | Dayou Du | 2024 | Efficient ML | arXiv non-exclusive | 83 |
| 2306.13549 | A Survey on Multimodal Large Language Models | Shukang Yin | 2023 | Multimodal | CC BY 4.0 | 251 |
| 2405.10739 | Efficient Multimodal Large Language Models: A Survey | Yizhang Jin | 2024 | Multimodal | arXiv non-exclusive | 227 |
| 2411.15296 | MME-Survey: A Comprehensive Survey on Evaluation of Multimodal LLMs | Chaoyou Fu | 2024 | Multimodal | arXiv non-exclusive | unverified |
| 2502.05151 | Transforming Science with Large Language Models: A Survey on AI-assisted Scientific Discovery, Experimentation, Content Generation, and Evaluation | Steffen Eger | 2025 | AI for science | CC BY 4.0 | 335 |
| 2508.14111 | From AI for Science to Agentic Science: A Survey on Autonomous Scientific Discovery | Jiaqi Wei | 2025 | AI for science | arXiv non-exclusive | unverified |

## Notes

- 7 of 22 are CC BY 4.0. Releasing short citing sentences from non-CC-BY surveys may still be acceptable as short excerpts with attribution, but that is a judgement, not a verified legal position; preferring CC BY keeps the release simple.
- CV and RL have one candidate each; the pool needs more there before a stratified draw.
- 2303.18223 was used as the extractor smoke test (21 files, 946 citing sentences, 2150 units, 3 keys missing from the bibliography).
