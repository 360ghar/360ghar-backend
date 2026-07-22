# Nerfstudio kitchen (indoor image dataset)

Room-scale multi-view **images + poses** for Gaussian splat training.

| Path | Contents |
|------|----------|
| `kitchen/` | Raw unpack from official kitchen.zip |
| `kitchen_ready/` | **Use this** — `images/` + scaled `transforms.json` |

Source: [nerfbaselines-data](https://huggingface.co/datasets/nerfbaselines/nerfbaselines-data) `nerfstudio/kitchen.zip`  
Docs: https://docs.nerf.studio/quickstart/existing_dataset.html

```bash
ns-train splatfacto --data data/nerfstudio_images/kitchen_ready
```
