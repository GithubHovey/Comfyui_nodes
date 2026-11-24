# tools

四视图相关的两个离线步骤。工作流在
`ComfyUI-Installs/ComfyUI/ComfyUI/user/default/workflows/`。

下文命令都在部署根目录（`<Root>`，例如 `D:\Comfy-Desktop`）下执行，先设一个变量：

```powershell
$S = "D:\Comfy-Desktop\ComfyUI-Shared"   # 换成部署时选的 Root 下的 ComfyUI-Shared
```

| 工作流 | 出什么 | 耗时 | 用途 |
|---|---|---|---|
| `游戏截图到手办四视图.json` | 四张独立视图，每张约 850×1800（1.5MP） | ≈ 9 分钟 | **成品**，角度由原截图决定，材质提示词拿满权重 |
| `游戏截图到手办四宫格.json` | 一张 2×2 四宫格，拆开每格约 512×1024 | ≈ 2.5 分钟 | 布局稿 / 预览，一次采样四格天然一致，但角度会被正面先验拉走 |

四宫格的上限是硬的：一张图 2MP 摊给四格，每格只剩 0.5MP，而且四格共用一份
reference latent，侧面会被拉回正面。要成品就用四视图那版。

## 四视图（成品）

把 `正面.png / 背面.png / 左侧.png / 右侧.png` 放进 `input/`，打开工作流点运行。
四张分别存到 `output/手办-正面_*.png` 等。

想拼一张展示图：

```powershell
python tools\tile4.py `
  --front $S\output\手办-正面_00006_.png `
  --back  $S\output\手办-背面_00007_.png `
  --left  $S\output\手办-左侧_00005_.png `
  --right $S\output\手办-右侧_00005_.png `
  --out $S\output\四视图-成品.png `
  --width 1440 --height 2880
```

改分辨率：四个「缩放图像（按总像素）」节点的 megapixels，默认 1.5。Qwen 在 1–2MP
之间最稳，超过 2MP 容易出重复和糊边。

## 四宫格（预览）

```powershell
python tools\tile4.py --dir $S\input `
  --out $S\input\四宫格-参考.png

# ComfyUI 里开「游戏截图到手办四宫格」，点运行
# 输出：$S\output\手办-四视图_00001_.png

python tools\split4.py --sheet <上面那张> --out-dir <目录> --check <目录>\check.png
```

## 两个约定

- **顺序固定**：正面 左上、背面 右上、左侧 左下、右侧 右下。`tile4.py` 和
  `split4.py` 共用这个顺序，改一个必须改另一个。
- **拆图不按正中间硬切**。模型经常把底座画过中线，硬切会把底座削掉。`split4.py`
  默认按连通域找出四个人物、各自裁到轮廓、再缩放到同一高度对齐基线；认不出四个人物
  才退回硬切（`--mode fixed`）。

## 参数

`tile4.py`

| 参数 | 默认 | 说明 |
|---|---|---|
| `--width/--height` | 1024×2048 | 参考图/拼版尺寸 |
| `--gap` | 24 | 格间白槽 |
| `--fit` | bottom | 每格底边对齐，接近真实四视图 |

`split4.py`

| 参数 | 默认 | 说明 |
|---|---|---|
| `--width/--height` | 512×1024 | 输出画布 |
| `--margin` | 12 | 四周留白 |
| `--mode` | auto | auto 按轮廓裁切；fixed 正中间硬切 |
| `--check` | — | 另存一张标注了裁切框的检查图 |

## 已知限制

- 四路之间材质会有轻微漂移（同一 seed / prompt 下通常可接受）。
- 四宫格版里左侧那格容易被转成 3/4，不是纯侧面。
- 图里有底座和棚拍阴影。要直接喂 Tripo，把提示词里「站在白色圆形底座上」删掉，
  换成「纯净白底，无底座、无投影」，否则底座和阴影会被烘进贴图。
