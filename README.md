# save-near-input

两个 ComfyUI 自定义节点，用于「读取图片并把生成结果保存回图片所在目录」。

## 节点

### Load Image (with dir)

和内置 `Load Image` 完全一样，额外多输出一个 `IMAGE_DIR`（字符串）。

- 输出 1：`image` (IMAGE)
- 输出 2：`mask` (MASK)
- 输出 3：`image_dir` (STRING) —— 这张图所在的绝对目录

### Save Image to Dir

把图片保存到指定目录。

| 输入 | 说明 |
|---|---|
| `images` | 要保存的图片 |
| `image_dir` | 目标目录，通常直接连 `Load Image (with dir)` 的 `image_dir` |
| `filename_prefix` | 文件名前缀，最终文件名为 `<前缀>_00001_.png`，重名自动递增 |
| `keep_preview_in_output` | 是否在 `output/near-input-preview/` 留一份副本，供 ComfyUI 界面显示缩略图 |

保存的 PNG 内嵌 `prompt` 与 `workflow` 元数据，拖回 ComfyUI 可还原工作流。

## 安装

把整个目录放到：

```
ComfyUI/custom_nodes/save-near-input/
```

重启 ComfyUI，节点出现在 `image` 分类下。

## 部署到新机器

`kit/` 里是整套工作区的重建脚本：模型清单、Desktop 配置模板、四个图片脚本。

```powershell
git clone https://github.com/GithubHovey/Comfyui_nodes.git C:\cn
C:\cn\kit\一键部署.bat
```

脚本会找到本机的 ComfyUI Desktop 实例，建共享目录、拉 `Comfyui_flows` 的工作流、
把 `roco-scene` 和 `kit/tools` 铺到位、改写 `settings.json`，最后按 `kit/models.json`
下载 20 个模型（共 78 GB）。中途断网直接重跑，会接着下。

| 参数 | 作用 |
|---|---|
| `-Root D:\Comfy-Desktop` | 模型、输出、工具放哪；不给就交互问一次 |
| `-Check` | 只体检：哪些模型缺、每个缺件影响哪些工作流 |
| `-SkipModels` | 只搞配置和代码，不下模型 |
| `-DryRun` | 打印计划，不落盘 |

前提：ComfyUI Desktop 已安装并启动过一次（脚本装不了 GUI）。模型从 ModelScope
优先、hf-mirror 回落，需要能上网。

部署完那一份 clone 就可以删了。以后更新在节点目录里做：

```powershell
cd ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\save-near-input
git pull
kit\一键部署.bat -SkipModels      :: 只更新节点、工具和配置，不动模型
```

## 说明

ComfyUI 的 `Load Image` 只从 `input` 目录读取，拖进去的图片会被复制到那里，
因此「跟随图片所在目录」的结果就是 `input` 目录。

如果要保存到其他位置（例如原始素材所在的 D 盘目录），直接把绝对路径填进
`Save Image to Dir` 的 `image_dir` 即可（此时不必连 `Load Image (with dir)`）。

## 版本

- 0.1.0 —— 初版：两个节点，支持自动跟随目录、递增命名、预览副本
