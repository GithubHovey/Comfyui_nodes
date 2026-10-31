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

## 说明

ComfyUI 的 `Load Image` 只从 `input` 目录读取，拖进去的图片会被复制到那里，
因此「跟随图片所在目录」的结果就是 `input` 目录。

如果要保存到其他位置（例如原始素材所在的 D 盘目录），直接把绝对路径填进
`Save Image to Dir` 的 `image_dir` 即可（此时不必连 `Load Image (with dir)`）。

## 版本

- 0.1.0 —— 初版：两个节点，支持自动跟随目录、递增命名、预览副本
