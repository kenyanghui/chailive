# chai-for-live · 拆书为生

RIA 便签读书法全库：**2255 本书 / 1713 本有拆页 / 19262 个拆页**，单文件架构、零外部依赖、双击即开、离线可用。

- 在线阅读：https://kenyanghui.github.io/chai-for-live/
- RIA 三段卡：R 原文 / I 讲解 / A 促动（+ a1/a2/a3 flags）
- 全局深度检索：19262 拆页主题懒加载索引
- 大书自动分片（《非暴力沟通》2153 拆页也不例外）
- 数据已脱敏发布（email/token 指纹三道防线，build.json 含确定性指纹）

## 架构

```
index.html        # 单文件 UI：L1 书索引（2255 本）内嵌
data/<bid>.js     # 每书一个分片：CHAI_DATA[bid] = {book, np, pb, idx, ms}
data/<bid>.pN.js  # 大书 part≥2：CHAI_PD["<bid>_<n>"]
data/topics.js    # 全局拆页主题索引 CHAI_TOPICS（懒加载）
covers/<id>.jpg   # 2229 张封面自托管
build.json        # 构建指纹（双跑一致性验证）
```

六矩阵节点并行提取 → reducer 汇聚（md5 对账 + 计数断言 2255/1713/19262）。
