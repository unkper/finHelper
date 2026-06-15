"""财经新闻标题与摘要自动翻译为简体中文（Argos Translate 离线翻译）。"""
import logging
import re
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
FROM_CODE = "en"
TO_CODE = "zh"
_package_lock = threading.Lock()
_package_ready: Optional[bool] = None


def _cjk_ratio(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 1.0
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / max(len(text), 1)


def needs_translation(text: str) -> bool:
    """中文占比偏低时视为需要翻译。"""
    return _cjk_ratio(text) < 0.25


def _is_package_installed() -> bool:
    try:
        import argostranslate.package as pkg
    except ImportError:
        return False
    return any(
        package.from_code == FROM_CODE and package.to_code == TO_CODE
        for package in pkg.get_installed_packages()
    )


def _ensure_en_zh_package() -> bool:
    """确保 en→zh 语言包已安装；首次会联网下载。"""
    global _package_ready
    if _package_ready is True:
        return True
    if _package_ready is False:
        return False

    with _package_lock:
        if _package_ready is True:
            return True
        if _package_ready is False:
            return False
        try:
            import argostranslate.package as pkg
        except ImportError:
            _package_ready = False
            return False

        if _is_package_installed():
            _package_ready = True
            return True

        try:
            pkg.update_package_index()
            available = pkg.get_available_packages()
            match = next(
                (
                    package
                    for package in available
                    if package.from_code == FROM_CODE and package.to_code == TO_CODE
                ),
                None,
            )
            if match is None:
                logger.warning("argostranslate: 未找到 en→zh 语言包")
                _package_ready = False
                return False
            pkg.install_from_path(match.download())
            _package_ready = True
            logger.info("argostranslate: en→zh 语言包安装完成")
            return True
        except Exception as exc:
            logger.warning("argostranslate: 安装 en→zh 语言包失败: %s", exc)
            _package_ready = False
            return False


def is_translation_available() -> bool:
    """是否已安装 Argos Translate（语言包可在首次翻译时自动下载）。"""
    try:
        import argostranslate.translate  # noqa: F401
    except ImportError:
        return False
    return True


def _translate_texts(texts: List[str]) -> List[str]:
    if not texts:
        return texts
    if not _ensure_en_zh_package():
        return texts

    import argostranslate.translate as argos_translate

    results: List[str] = []
    for text in texts:
        try:
            results.append(argos_translate.translate(text, FROM_CODE, TO_CODE))
        except Exception as exc:
            logger.debug("argostranslate 翻译失败: %s", exc)
            results.append(text)
    return results


def translate_news_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将英文新闻标题与摘要译为简体中文；未安装依赖或已是中文则原样返回。"""
    if not items or not is_translation_available():
        return items

    merged = [dict(item) for item in items]
    pending: List[tuple[int, str, str]] = []
    for index, item in enumerate(merged):
        for field in ("title", "summary"):
            text = str(item.get(field) or "").strip()
            if needs_translation(text):
                pending.append((index, field, text))

    if not pending:
        return merged

    translated = _translate_texts([text for _, _, text in pending])
    for (index, field, original), new_text in zip(pending, translated):
        cleaned = (new_text or "").strip()
        if cleaned and cleaned != original:
            merged[index][field] = cleaned
            merged[index]["translated"] = True

    return merged
