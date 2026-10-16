"""Native EfficientAD-S components adapted for modern PyTorch.

The implementation keeps the reference EfficientAD architecture and losses,
but disables the optional general-image penalty when no general-image dataset
is supplied. The reference teacher remains a separately identified artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Any

import numpy as np


class EfficientADDependencyError(RuntimeError):
    pass


def _torch():
    try:
        import torch
        from PIL import Image, ImageDraw
        from torchvision import transforms
    except ImportError as exc:
        raise EfficientADDependencyError("native EfficientAD requires torch, torchvision, and Pillow") from exc
    return torch, Image, ImageDraw, transforms


def pdn_small(out_channels: int = 384, padding: bool = False):
    torch, _, _, _ = _torch()
    nn = torch.nn
    pad = 1 if padding else 0
    return nn.Sequential(
        nn.Conv2d(3, 128, 4, padding=3 * pad), nn.ReLU(inplace=True),
        nn.AvgPool2d(2, 2, padding=pad), nn.Conv2d(128, 256, 4, padding=3 * pad),
        nn.ReLU(inplace=True), nn.AvgPool2d(2, 2, padding=pad),
        nn.Conv2d(256, 256, 3, padding=pad), nn.ReLU(inplace=True),
        nn.Conv2d(256, out_channels, 4),
    )


def autoencoder(out_channels: int = 384):
    torch, _, _, _ = _torch()
    nn = torch.nn
    return nn.Sequential(
        nn.Conv2d(3, 32, 4, 2, 1), nn.ReLU(True), nn.Conv2d(32, 32, 4, 2, 1), nn.ReLU(True),
        nn.Conv2d(32, 64, 4, 2, 1), nn.ReLU(True), nn.Conv2d(64, 64, 4, 2, 1), nn.ReLU(True),
        nn.Conv2d(64, 64, 4, 2, 1), nn.ReLU(True), nn.Conv2d(64, 64, 8),
        nn.Upsample(size=3, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=8, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=15, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=32, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=63, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=127, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 4, padding=2), nn.ReLU(True), nn.Dropout(.2),
        nn.Upsample(size=56, mode="bilinear", align_corners=False), nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(True), nn.Conv2d(64, out_channels, 3, padding=1),
    )


@dataclass(frozen=True)
class EfficientADCheckpoint:
    path: Path
    category: str
    teacher_source: str
    teacher_sha256: str
    image_size: tuple[int, int] = (256, 256)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_teacher(path: str | Path, device: Any):
    torch, _, _, _ = _torch()
    model = pdn_small(384, padding=False).to(device)
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    state = checkpoint.state_dict() if hasattr(checkpoint, "state_dict") else checkpoint.get("state_dict", checkpoint)
    model.load_state_dict(state)
    model.eval()
    return model


def image_transform(size: tuple[int, int] = (256, 256), jitter: bool = False):
    _, _, _, transforms = _torch()
    ops = [transforms.Resize(size)]
    if jitter:
        ops.append(transforms.RandomChoice([transforms.ColorJitter(brightness=.2), transforms.ColorJitter(contrast=.2), transforms.ColorJitter(saturation=.2)]))
    ops.extend([transforms.ToTensor(), transforms.Normalize([.485, .456, .406], [.229, .224, .225])])
    return transforms.Compose(ops)


@dataclass
class NativeRun:
    category: str
    steps: int
    checkpoint: Path
    scores: list[float]
    labels: list[int]


def _teacher_stats(teacher, loader, device):
    torch, _, _, _ = _torch()
    values = []
    teacher.eval()
    with torch.no_grad():
        for images in loader:
            values.append(teacher(images.to(device)).mean(dim=(0, 2, 3)))
    mean = torch.stack(values).mean(0)[None, :, None, None]
    distances = []
    with torch.no_grad():
        for images in loader:
            output = teacher(images.to(device))
            distances.append(((output - mean) ** 2).mean(dim=(0, 2, 3)))
    std = torch.sqrt(torch.stack(distances).mean(0))[None, :, None, None].clamp_min(1e-6)
    return mean.to(device), std.to(device)


def predict(image, teacher, student, ae, mean, std, q_values=None):
    torch, _, _, _ = _torch()
    with torch.no_grad():
        teacher_output = (teacher(image) - mean) / std
        student_output = student(image)
        local_map = ((teacher_output - student_output[:, :384]) ** 2).mean(1, keepdim=True)
        global_map = ((ae(image) - student_output[:, 384:]) ** 2).mean(1, keepdim=True)
        if q_values is not None:
            st0, st1, ae0, ae1 = q_values
            local_map = .1 * (local_map - st0) / (st1 - st0).clamp_min(1e-6)
            global_map = .1 * (global_map - ae0) / (ae1 - ae0).clamp_min(1e-6)
        combined = .5 * local_map + .5 * global_map
        combined = torch.nn.functional.pad(combined, (4, 4, 4, 4))
        return combined, local_map, global_map


def overlay_image(image_path: str | Path, anomaly_map: np.ndarray, output_path: str | Path) -> None:
    _, Image, _, _ = _torch()
    image = Image.open(image_path).convert("RGB")
    heat = Image.fromarray(np.uint8(np.clip(anomaly_map, 0, 1) * 255)).resize(image.size)
    heat = heat.convert("RGB")
    red = Image.new("RGB", image.size, (255, 0, 0))
    blended = Image.blend(image, Image.blend(heat, red, .65), .35)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    blended.save(output_path)


def set_seed(seed: int) -> None:
    torch, _, _, _ = _torch()
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)


def train_category(
    dataset_root: str | Path,
    category: str,
    teacher_path: str | Path,
    output_dir: str | Path,
    *,
    steps: int = 70_000,
    batch_size: int = 1,
    device: str = "cuda",
    seed: int = 42,
) -> NativeRun:
    """Train one category using the reference-teacher, MVTec-only variant."""
    torch, Image, _, _ = _torch()
    from torch.utils.data import DataLoader, Dataset

    if steps < 1 or batch_size < 1:
        raise ValueError("steps and batch_size must be positive")
    set_seed(seed)
    target = torch.device(device if device == "cpu" or torch.cuda.is_available() else "cpu")
    root = Path(dataset_root) / category / "train" / "good"
    paths = sorted(root.glob("*.png"))
    if not paths:
        raise ValueError(f"no training images found for {category}: {root}")
    transform = image_transform()

    class Images(Dataset):
        def __len__(self): return len(paths)
        def __getitem__(self, index):
            with Image.open(paths[index]) as image:
                return transform(image.convert("RGB"))

    loader = DataLoader(Images(), batch_size=batch_size, shuffle=True, num_workers=0, drop_last=True)
    teacher = load_teacher(teacher_path, target)
    mean, std = _teacher_stats(teacher, loader, target)
    student = pdn_small(768).to(target).train()
    ae = autoencoder().to(target).train()
    optimizer = torch.optim.Adam([*student.parameters(), *ae.parameters()], lr=1e-4, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=max(1, int(.95 * steps)), gamma=.1)
    iterator = iter(loader)
    for _ in range(steps):
        try:
            image = next(iterator)
        except StopIteration:
            iterator = iter(loader); image = next(iterator)
        image = image.to(target)
        with torch.no_grad(): teacher_output = (teacher(image) - mean) / std
        student_output = student(image)
        distance = (teacher_output - student_output[:, :384]) ** 2
        hard = torch.quantile(distance, .999)
        loss_st = distance[distance >= hard].mean()
        ae_output = ae(image)
        with torch.no_grad(): teacher_ae = (teacher(image) - mean) / std
        loss_ae = ((teacher_ae - ae_output) ** 2).mean()
        loss_stae = ((ae_output - student_output[:, 384:]) ** 2).mean()
        loss = loss_st + loss_ae + loss_stae
        optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step(); scheduler.step()
    student.eval(); ae.eval()
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / f"efficientad_s_{category}.pt"
    torch.save({"student": student.state_dict(), "autoencoder": ae.state_dict(), "teacher_mean": mean.cpu(), "teacher_std": std.cpu(), "category": category, "teacher_source": str(teacher_path), "teacher_sha256": sha256_file(teacher_path), "steps": steps, "seed": seed, "variant": "EfficientAD-S-ReferenceTeacher-MVTecOnly"}, checkpoint)
    return NativeRun(category, steps, checkpoint, [], [])


def infer_checkpoint(checkpoint_path: str | Path, teacher_path: str | Path, image_path: str | Path, device: str = "cuda") -> tuple[float, np.ndarray]:
    """Reload a native checkpoint and return score plus an input-sized map."""
    torch, Image, _, _ = _torch()
    target = torch.device(device if device == "cpu" or torch.cuda.is_available() else "cpu")
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    teacher = load_teacher(teacher_path, target)
    student = pdn_small(768).to(target); student.load_state_dict(payload["student"]); student.eval()
    ae = autoencoder().to(target); ae.load_state_dict(payload["autoencoder"]); ae.eval()
    mean = payload["teacher_mean"].to(target); std = payload["teacher_std"].to(target)
    transform = image_transform()
    with Image.open(image_path) as source:
        original = source.convert("RGB")
        width, height = original.size
        image = transform(original)[None].to(target)
    combined, _, _ = predict(image, teacher, student, ae, mean, std)
    combined = torch.nn.functional.interpolate(combined, (height, width), mode="bilinear", align_corners=False)[0, 0]
    anomaly_map = combined.detach().cpu().numpy().astype(np.float32)
    return float(anomaly_map.max()), anomaly_map
