import argparse
import json
from pathlib import Path
import sys

from .core import compile_album, ValidationError
from .export import export_csv, export_manifest, export_pdf


def main():
    parser = argparse.ArgumentParser(description="Album Factory — локальный контрольный макет")
    parser.add_argument("order", type=Path, help="JSON заказа, пути фото относительно его папки")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--font", required=True, type=Path, help="TTF со всеми нужными символами")
    args = parser.parse_args()
    try:
        data = json.loads(args.order.read_text(encoding="utf-8"))
        album = compile_album(data, args.order.parent)
        args.output.mkdir(parents=True, exist_ok=True)
        outputs = [args.output / name for name in ("album-proof.pdf", "selections.csv", "manifest.json")]
        if any(path.exists() for path in outputs):
            raise ValidationError("Файлы результата уже существуют; выберите новую папку версии")
        export_pdf(album, outputs[0], args.font)
        export_csv(album, outputs[1])
        export_manifest(album, outputs[2])
        print(f"Создан контрольный PDF: {len(album.pages)} стр., {len(album.people)} персон, 1 макет")
        print(f"Количество экземпляров: {album.copies}. Версия: {album.revision[:12]}")
        for warning in album.warnings:
            print(f"Предупреждение: {warning}")
        print("Это контрольный PDF, не утверждённый файл для типографии.")
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
