# Third-party components

本清单最后核对于2026-08-21。项目本身使用MIT许可证；依赖及数据集仍分别受各自条款约束。

| 组件 | 用途 | 当前项目约束 |
| --- | --- | --- |
| scikit-learn | 参考Recipe中的数据集、模型、切分与指标 | BSD-3-Clause；作为安装依赖，不复制其源码 |
| Pillow | 用户图片解码、EXIF方向处理与缩放 | HPND；作为安装依赖，不复制其源码 |
| NumPy | 数组计算，由scikit-learn依赖引入 | 作为安装依赖 |
| SciPy | 科学计算，由scikit-learn依赖引入 | 作为安装依赖 |
| Joblib | 保存参考模型，由scikit-learn依赖引入 | 只加载可信且哈希匹配的本地产物 |
| Digits dataset | 1,797张8×8手写数字教学数据 | scikit-learn文档注明其为UCI Optical Recognition of Handwritten Digits测试集副本；运行时加载，不在仓库复制数据 |
| UCI Wine Quality | 4,898条白葡萄酒与1,599条红葡萄酒理化指标及质量分数 | CC BY 4.0；只在真实场景验证脚本运行时由用户下载，仓库不再分发数据 |
| DeepSeek Harness SDK与Cordis | 可选DSH工具bundle的插件协议和运行时类型 | MIT；通过npm开发依赖使用，不复制或修改DeepSeek Harness源码 |

核对来源：

- scikit-learn许可证：https://github.com/scikit-learn/scikit-learn/blob/main/COPYING
- Pillow许可证：https://github.com/python-pillow/Pillow/blob/main/LICENSE
- `load_digits`数据说明：https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html
- UCI Wine Quality数据与许可：https://archive.ics.uci.edu/dataset/186/wine+quality
- DeepSeek Harness源码与许可证：https://github.com/deepseek-ai/deepseek-harness

模型Recipe后续引入新框架、预训练权重或数据集时，必须记录代码许可、权重许可、数据许可、来源URL、检索日期和是否允许再分发。
