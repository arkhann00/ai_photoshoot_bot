# src/db/repositories/styles.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, delete, text
from sqlalchemy.exc import IntegrityError

from src.db.session import async_session, engine
from src.db.models import StyleCategory, StylePrompt
from src.db.enums import StyleGender
from src.db.migrations import _is_postgres, _postgres_fix_sequences


async def count_active_styles() -> int:
    async with async_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(StylePrompt).where(StylePrompt.is_active == True)  # noqa: E712
        )
        return int(total or 0)


async def get_style_by_offset(offset: int) -> Optional[StylePrompt]:
    async with async_session() as session:
        result = await session.execute(
            select(StylePrompt)
            .where(StylePrompt.is_active == True)  # noqa: E712
            .order_by(StylePrompt.id.asc())
            .offset(offset)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_style_prompt_by_id(style_id: int) -> Optional[StylePrompt]:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        return style


async def get_all_style_prompts(include_inactive: bool = True) -> list[StylePrompt]:
    async with async_session() as session:
        stmt = select(StylePrompt)
        if not include_inactive:
            stmt = stmt.where(StylePrompt.is_active == True)  # noqa: E712
        stmt = stmt.order_by(StylePrompt.category_id.asc(), StylePrompt.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def delete_style_prompt(style_id: int) -> bool:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        if style is None:
            return False
        await session.delete(style)
        await session.commit()
        return True


async def create_style_category(
    title: str,
    description: str,
    image_filename: str,
    gender: StyleGender,
    is_active: bool = True,
) -> StyleCategory:
    async with async_session() as session:
        category = StyleCategory(
            title=title,
            description=description,
            image_filename=image_filename,
            gender=gender,
            is_active=is_active,
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)
        return category


async def get_style_category_by_id(category_id: int) -> Optional[StyleCategory]:
    async with async_session() as session:
        category = await session.get(StyleCategory, category_id)
        return category


async def get_style_categories_for_gender(gender: StyleGender) -> list[StyleCategory]:
    async with async_session() as session:
        result = await session.execute(
            select(StyleCategory)
            .where(
                StyleCategory.gender == gender,
                StyleCategory.is_active == True,  # noqa: E712
            )
            .order_by(StyleCategory.sort_order.asc(), StyleCategory.id.asc())
        )
        return list(result.scalars().all())


async def get_all_style_categories(include_inactive: bool = False) -> list[StyleCategory]:
    async with async_session() as session:
        stmt = select(StyleCategory)
        if not include_inactive:
            stmt = stmt.where(StyleCategory.is_active == True)  # noqa: E712
        stmt = stmt.order_by(StyleCategory.sort_order.asc(), StyleCategory.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _is_style_prompts_pk_duplicate(e: IntegrityError) -> bool:
    s = str(e)
    return ("duplicate key value violates unique constraint" in s) and ("style_prompts_pkey" in s)


async def create_style_prompt(
    title: str,
    description: str,
    prompt: str,
    image_filename: str,
    category_id: int,
) -> StylePrompt:
    async with async_session() as session:
        result = await session.execute(select(StyleCategory).where(StyleCategory.id == category_id))
        category = result.scalar_one_or_none()
        if category is None:
            raise ValueError(f"StyleCategory with id={category_id} not found")

        async def _insert_once() -> StylePrompt:
            obj = StylePrompt(
                title=title,
                description=description,
                prompt=prompt,
                image_filename=image_filename,
                category_id=category.id,
                gender=category.gender,
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
            return obj

        try:
            return await _insert_once()
        except IntegrityError as e:
            await session.rollback()
            if _is_style_prompts_pk_duplicate(e):
                async with engine.begin() as conn:
                    if _is_postgres(conn):
                        await _postgres_fix_sequences(conn)
                return await _insert_once()
            raise


async def get_styles_for_category(category_id: int) -> list[StylePrompt]:
    async with async_session() as session:
        result = await session.execute(
            select(StylePrompt)
            .where(
                StylePrompt.category_id == category_id,
                StylePrompt.is_active == True,  # noqa: E712
            )
            .order_by(StylePrompt.id.asc())
        )
        return list(result.scalars().all())


async def get_styles_by_category_and_gender(category_id: int, gender: StyleGender) -> list[StylePrompt]:
    async with async_session() as session:
        stmt = (
            select(StylePrompt)
            .where(
                StylePrompt.is_active == True,  # noqa: E712
                StylePrompt.category_id == category_id,
                StylePrompt.gender == gender,
            )
            .order_by(StylePrompt.id.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_styles_for_category_ids(category_ids: list[int]) -> list[StylePrompt]:
    if not category_ids:
        return []
    async with async_session() as session:
        stmt = (
            select(StylePrompt)
            .where(
                StylePrompt.is_active == True,  # noqa: E712
                StylePrompt.category_id.in_(category_ids),
            )
            .order_by(StylePrompt.category_id.asc(), StylePrompt.id.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_styles_for_category_ids_and_gender(category_ids: list[int], gender: StyleGender) -> list[StylePrompt]:
    if not category_ids:
        return []
    async with async_session() as session:
        stmt = (
            select(StylePrompt)
            .where(
                StylePrompt.is_active == True,  # noqa: E712
                StylePrompt.category_id.in_(category_ids),
                StylePrompt.gender == gender,
            )
            .order_by(StylePrompt.category_id.asc(), StylePrompt.id.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
async def increment_style_usage(style_id: int, delta: int = 1) -> None:
    if delta <= 0:
        return

    async with async_session() as session:
        await session.execute(
            text("UPDATE style_prompts SET usage_count = usage_count + :d WHERE id = :id"),
            {"d": delta, "id": style_id},
        )
        await session.commit()
        
async def set_style_is_new(style_id: int, is_new: bool) -> Optional[StylePrompt]:
    async with async_session() as session:
        obj = await session.get(StylePrompt, style_id)
        if obj is None:
            return None
        obj.is_new = is_new
        await session.commit()
        await session.refresh(obj)
        return obj