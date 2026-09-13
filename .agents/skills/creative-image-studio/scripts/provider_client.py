#!/usr/bin/env python3
"""OpenAI-compatible 图片 API 内部适配器。

本脚本只供 Agent 内部实现使用，不承诺为稳定的用户命令行接口。
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping


class ProviderError(RuntimeError):
    pass


class ProviderChoiceRequired(ProviderError):
    def __init__(self, providers: Iterable[str]):
        self.providers = sorted(providers)
        super().__init__("存在多个可用平台，请选择：" + ", ".join(self.providers))


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("providers"), dict):
        raise ProviderError(f"不支持的平台配置格式：{config_path}")
    return data


def provider_is_eligible(
    profile: Mapping[str, Any], capability: str | Iterable[str], environ: Mapping[str, str]
) -> bool:
    if not profile.get("enabled", True):
        return False
    required = [capability] if isinstance(capability, str) else list(capability)
    if any(not profile.get("capabilities", {}).get(item, False) for item in required):
        return False
    key_name = profile.get("api_key_env")
    return bool(key_name and environ.get(str(key_name)))


def select_provider(
    config: Mapping[str, Any],
    capability: str | Iterable[str],
    requested: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    environ = environ or os.environ
    providers = config.get("providers", {})
    if requested:
        if requested not in providers:
            raise ProviderError(f"未知的平台配置：{requested}")
        profile = providers[requested]
        if not provider_is_eligible(profile, capability, environ):
            required_key = profile.get("api_key_env", "已配置的 API Key")
            required_caps = [capability] if isinstance(capability, str) else list(capability)
            raise ProviderError(
                f"平台“{requested}”已禁用、缺少能力 {required_caps}，"
                f"或缺少环境变量“{required_key}”。"
            )
        return requested, dict(profile)

    default_name = config.get("default_provider")
    if default_name in providers and provider_is_eligible(
        providers[default_name], capability, environ
    ):
        return str(default_name), dict(providers[default_name])

    eligible = {
        name: profile
        for name, profile in providers.items()
        if provider_is_eligible(profile, capability, environ)
    }
    if not eligible:
        return None
    if len(eligible) > 1:
        raise ProviderChoiceRequired(eligible)
    name, profile = next(iter(eligible.items()))
    return str(name), dict(profile)


def _safe_stem(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return value or "image"


def versioned_path(directory: Path, stem: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(stem)
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-v{index}{suffix}"
        index += 1
    return candidate


def encode_multipart(
    fields: Mapping[str, Any], files: Iterable[tuple[str, Path]]
) -> tuple[bytes, str]:
    boundary = f"creative-image-studio-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, path in files:
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def image_data_uri(path: str | Path) -> str:
    image_path = Path(path)
    if not image_path.is_file():
        raise ProviderError(f"输入图片不存在：{image_path}")
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        raise ProviderError(f"输入文件不是可识别的图片：{image_path}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def set_nested_value(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = [part for part in dotted_path.split(".") if part]
    if not parts:
        raise ProviderError("配置的 JSON 图片字段为空")
    current: dict[str, Any] = payload
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            existing = {}
            current[part] = existing
        if not isinstance(existing, dict):
            raise ProviderError(f"配置的 JSON 字段与非对象值冲突：{part}")
        current = existing
    current[parts[-1]] = value


def image_dimensions(path: str | Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ProviderError("从输入图推导编辑尺寸需要 Pillow") from exc
    try:
        with Image.open(path) as image:
            return image.size
    except OSError as exc:
        raise ProviderError(f"无法读取输入图尺寸：{path}") from exc


def normalize_mask(
    mask_path: str | Path, output_path: str | Path, semantics: str
) -> Path:
    from PIL import Image, ImageOps

    source = Image.open(mask_path).convert("L")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if semantics == "white_edit":
        source.save(output)
    elif semantics == "black_edit":
        ImageOps.invert(source).save(output)
    elif semantics == "transparent_edit":
        rgba = Image.new("RGBA", source.size, (255, 255, 255, 255))
        rgba.putalpha(ImageOps.invert(source))
        rgba.save(output)
    else:
        raise ProviderError(f"未知遮罩语义：{semantics}")
    return output


def composite_masked_edit(
    original_path: str | Path,
    edited_path: str | Path,
    white_edit_mask: str | Path,
    output_path: str | Path,
) -> Path:
    from PIL import Image

    original = Image.open(original_path).convert("RGBA")
    edited = Image.open(edited_path).convert("RGBA")
    mask = Image.open(white_edit_mask).convert("L")
    if edited.size != original.size or mask.size != original.size:
        raise ProviderError(
            f"遮罩编辑尺寸不一致：原图={original.size}，编辑图={edited.size}，遮罩={mask.size}"
        )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.composite(edited, original, mask).save(output)
    return output


class OpenAIImageClient:
    def __init__(self, profile: Mapping[str, Any], environ: Mapping[str, str] | None = None):
        self.profile = dict(profile)
        self.environ = environ or os.environ
        key_name = str(self.profile.get("api_key_env", ""))
        self.api_key = self.environ.get(key_name, "")
        if not self.api_key:
            raise ProviderError(f"缺少必需的环境变量：{key_name}")

    def _url(self, operation: str) -> str:
        base = str(self.profile.get("base_url", "")).rstrip("/")
        endpoint = str(self.profile.get("endpoints", {}).get(operation, ""))
        if not base or not endpoint:
            raise ProviderError(f"平台缺少 {operation} 的 URL 配置")
        url = base + "/" + endpoint.lstrip("/")
        if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
            raise ProviderError("平台 URL 必须使用 http 或 https")
        return url

    def _headers(self, content_type: str) -> dict[str, str]:
        headers = {str(k): str(v) for k, v in self.profile.get("headers", {}).items()}
        auth_header = str(self.profile.get("auth_header", "Authorization"))
        prefix = str(self.profile.get("auth_prefix", "Bearer "))
        headers[auth_header] = prefix + self.api_key
        headers["Content-Type"] = content_type
        headers["Accept"] = "application/json, image/*"
        return headers

    def _request(self, operation: str, body: bytes, content_type: str) -> tuple[bytes, str]:
        request = urllib.request.Request(
            self._url(operation),
            data=body,
            headers=self._headers(content_type),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read(), response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            detail = detail.replace(self.api_key, "[REDACTED]")
            raise ProviderError(f"图片 API 返回 HTTP {exc.code}：{detail[:2000]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"图片 API 连接失败：{exc.reason}") from exc

    def generate(self, prompt: str, **parameters: Any) -> tuple[bytes, str]:
        if not self.profile.get("capabilities", {}).get("generate", False):
            raise ProviderError("所选平台不支持图片生成")
        payload = dict(self.profile.get("generation_defaults", {}))
        payload.update({k: v for k, v in parameters.items() if v is not None})
        payload["prompt"] = prompt
        payload.setdefault("model", self.profile.get("models", {}).get("generate"))
        return self._request(
            "generate", json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"
        )

    def edit(
        self,
        prompt: str,
        image_paths: Iterable[str | Path],
        mask_path: str | Path | None = None,
        **parameters: Any,
    ) -> tuple[bytes, str]:
        caps = self.profile.get("capabilities", {})
        if not caps.get("edit", False):
            raise ProviderError("所选平台不支持图片编辑")
        if mask_path and not caps.get("mask", False):
            raise ProviderError("所选平台不支持遮罩局部编辑")
        fields = copy.deepcopy(self.profile.get("edit_defaults", {}))
        fields.update({k: v for k, v in parameters.items() if v is not None})
        fields["prompt"] = prompt
        fields.setdefault("model", self.profile.get("models", {}).get("edit"))
        paths = [Path(p) for p in image_paths]
        if not paths:
            raise ProviderError("图片编辑至少需要一张输入图")
        if len(paths) > 1 and not caps.get("reference_images", False):
            raise ProviderError("所选平台不支持多张参考图")

        transport = str(self.profile.get("edit_transport", "multipart"))
        if transport == "json_data_uri":
            if mask_path:
                raise ProviderError("JSON Data URI 编辑传输不支持遮罩")
            if self.profile.get("edit_size_from_input", False) and not fields.get("size"):
                width, height = image_dimensions(paths[0])
                fields["size"] = f"{width}x{height}"
            image_field = str(self.profile.get("edit_image_field", "image"))
            set_nested_value(fields, image_field, [image_data_uri(path) for path in paths])
            body = json.dumps(fields, ensure_ascii=False).encode("utf-8")
            return self._request("edit", body, "application/json")
        if transport != "multipart":
            raise ProviderError(f"未知编辑传输方式：{transport}")

        file_fields = [("image" if len(paths) == 1 else "image[]", p) for p in paths]
        if mask_path:
            file_fields.append(("mask", Path(mask_path)))
        body, content_type = encode_multipart(fields, file_fields)
        return self._request("edit", body, content_type)


def persist_response(
    body: bytes,
    content_type: str,
    output_dir: str | Path,
    stem: str = "image",
    output_format: str = "png",
) -> list[Path]:
    output_dir = Path(output_dir)
    if content_type.startswith("image/"):
        suffix = mimetypes.guess_extension(content_type) or f".{output_format}"
        target = versioned_path(output_dir, stem, suffix)
        target.write_bytes(body)
        return [target]

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("平台响应既不是 JSON，也不是图片字节") from exc
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ProviderError(f"平台响应中没有图片数据：{str(payload)[:1000]}")

    outputs: list[Path] = []
    for index, item in enumerate(data, start=1):
        item_stem = stem if len(data) == 1 else f"{stem}-{index}"
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"], validate=True)
            target = versioned_path(output_dir, item_stem, f".{output_format}")
            target.write_bytes(raw)
        elif item.get("url"):
            url = str(item["url"])
            if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
                raise ProviderError(f"图片 URL 使用不支持的协议：{url[:100]}")
            request = urllib.request.Request(url, headers={"Accept": "image/*"})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    raw = response.read()
                    mime = response.headers.get_content_type()
            except urllib.error.URLError as exc:
                raise ProviderError(f"无法下载平台返回的图片 URL：{exc.reason}") from exc
            suffix = mimetypes.guess_extension(mime) or f".{output_format}"
            target = versioned_path(output_dir, item_stem, suffix)
            target.write_bytes(raw)
        else:
            raise ProviderError(f"第 {index} 个图片项既没有 b64_json，也没有 url")
        outputs.append(target)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAI-compatible 图片接口内部适配器")
    parser.add_argument("--config", required=True)
    parser.add_argument("--provider")
    sub = parser.add_subparsers(dest="operation", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--prompt", required=True)
    gen.add_argument("--out-dir", required=True)
    gen.add_argument("--stem", default="generated")
    gen.add_argument("--size")
    gen.add_argument("--ratio")
    gen.add_argument("--quality")
    gen.add_argument("--n", type=int)
    edit = sub.add_parser("edit")
    edit.add_argument("--prompt", required=True)
    edit.add_argument("--image", action="append", required=True)
    edit.add_argument("--mask")
    edit.add_argument("--size")
    edit.add_argument("--ratio")
    edit.add_argument("--out-dir", required=True)
    edit.add_argument("--stem", default="edited")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    required_capabilities: str | list[str] = args.operation
    if args.operation == "edit" and args.mask:
        required_capabilities = ["edit", "mask"]
    chosen = select_provider(config, required_capabilities, args.provider)
    if not chosen:
        print(json.dumps({"mode": "advisor", "reason": "没有可用平台"}, ensure_ascii=False))
        return 3
    name, profile = chosen
    client = OpenAIImageClient(profile)
    if args.operation == "generate":
        body, mime = client.generate(
            args.prompt, size=args.size, ratio=args.ratio, quality=args.quality, n=args.n
        )
    else:
        body, mime = client.edit(
            args.prompt, args.image, args.mask, size=args.size, ratio=args.ratio
        )
    outputs = persist_response(body, mime, args.out_dir, args.stem)
    print(json.dumps({"provider": name, "outputs": [str(p) for p in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderError as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2)
