# ISSUE


1. 刚更新 logging，现在每个 interview 会生成 2种 log，分别为后台log，和 dialogue log。（未测试）

2. 因为更新了 dialogue log, ai 评测部分其实可以节约掉一个 STT 模块的费用调用，直接用 LLM 即可。