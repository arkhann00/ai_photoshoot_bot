from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import async_session
from src.db.models import StyleCategory, StylePrompt, UserAvatar


def _norm_basename(name: str) -> str:
    return os.path.basename((name or "").strip())


def _collect_keep_names(*names: str) -> Set[str]:
    return {n for n in (_norm_basename(x) for x in names) if n}


async def _fetch_used_sets(session: AsyncSession) -> Tuple[Set[str], Set[str]]:
    """
    Возвращает:
      used_names: имена файлов, которые надо сохранить (с расширением)
      used_stems: имена без расширения, которые надо сохранить (например file_id)
    """
    used_names: Set[str] = set()
    used_stems: Set[str] = set()

    # ---- style_categories.image_filename ----
    res = await session.execute(select(StyleCategory.image_filename))
    for (fname,) in res.all():
        n = _norm_basename(fname)
        if n:
            used_names.add(n)

    # ---- style_prompts.image_filename (nullable) ----
    res = await session.execute(
        select(StylePrompt.image_filename).where(StylePrompt.image_filename.isnot(None))
    )
    for (fname,) in res.all():
        n = _norm_basename(fname)
        if n:
            used_names.add(n)

    # ---- user_avatars.file_id ----
    # Если ты сохраняешь аватары на диск под именем file_id(.ext),
    # то держим и stem=file_id, и варианты с расширениями.
    res = await session.execute(select(UserAvatar.file_id))
    common_exts = (".jpg", ".jpeg", ".png", ".webp")
    for (file_id,) in res.all():
        fid = (file_id or "").strip()
        if not fid:
            continue
        used_stems.add(fid)
        for ext in common_exts:
            used_names.add(f"{fid}{ext}")

    return used_names, used_stems


def _iter_files(img_dir: Path) -> Iterable[Path]:
    # только файлы в корне img (без рекурсии)
    for p in img_dir.iterdir():
        if p.is_file():
            yield p


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup unused files in ./img based on DB references.")
    parser.add_argument("--img-dir", default="img", help="Path to img directory (default: img)")
    parser.add_argument("--apply", action="store_true", help="Actually delete files. Without this flag - dry run.")
    parser.add_argument(
        "--keep",
        nargs="*",
        default=[],
        help="Extra filenames to keep (exact basenames). Example: --keep .gitkeep cover.jpg",
    )

    args = parser.parse_args()
    img_dir = Path(args.img_dir).resolve()

    if not img_dir.exists() or not img_dir.is_dir():
        raise SystemExit(f"img dir not found: {img_dir}")

    extra_keep = _collect_keep_names(*args.keep)

    async def runner() -> None:
        async with async_session() as session:
            used_names, used_stems = await _fetch_used_sets(session)

        used_names |= extra_keep  # ручные исключения

        existing_files = list(_iter_files(img_dir))

        to_delete: list[Path] = []
        kept: list[Path] = []

        for p in existing_files:
            if p.name in used_names or p.stem in used_stems:
                kept.append(p)
            else:
                to_delete.append(p)

        print(f"IMG DIR: {img_dir}")
        print(f"USED NAMES (with ext): {len(used_names)}")
        print(f"USED STEMS (no ext):  {len(used_stems)}")
        print(f"FILES ON DISK:        {len(existing_files)}")
        print(f"TO DELETE:            {len(to_delete)}")
        print()

        if to_delete:
            print("Will delete:" if not args.apply else "Deleting:")
            for p in sorted(to_delete, key=lambda x: x.name.lower()):
                print(f" - {p.name}")

        if args.apply and to_delete:
            for p in to_delete:
                try:
                    p.unlink()
                except Exception as e:
                    print(f"ERROR deleting {p.name}: {e}")

            print("\nDone.")

    import asyncio
    asyncio.run(runner())
