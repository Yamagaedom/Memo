"""Personal todo app implemented with Streamlit."""

from __future__ import annotations

import html
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st


APP_TITLE = "오늘의 할 일"
CATEGORIES = ("업무", "개인", "공부")
FILTERS = ("전체", *CATEGORIES)
AUTO_CATEGORY = "자동 분류"
CATEGORY_OPTIONS = (AUTO_CATEGORY, *CATEGORIES)
MAX_TITLE_LENGTH = 200
DATA_FILE = Path(__file__).with_name(".todo-data.json")
DATA_LOCK = threading.Lock()

CATEGORY_META = {
    "업무": {"icon": "▣", "class": "work"},
    "개인": {"icon": "●", "class": "personal"},
    "공부": {"icon": "◆", "class": "study"},
}

CATEGORY_KEYWORDS = {
    "업무": (
        "업무", "회의", "보고서", "프로젝트", "고객", "이메일", "메일", "발표",
        "마감", "출근", "팀", "회의록", "계약", "견적", "결재", "거래처",
    ),
    "개인": (
        "개인", "운동", "장보기", "병원", "약속", "청소", "빨래", "가족",
        "친구", "여행", "예약", "요리", "쇼핑", "은행", "집", "생활",
    ),
    "공부": (
        "공부", "학습", "강의", "과제", "시험", "복습", "독서", "책", "코딩",
        "논문", "자격증", "단어", "수업", "연습", "문제집", "세미나",
    ),
}


def is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def classify_category(title: str) -> str:
    """Classify a title by keyword score, defaulting to the personal category."""
    normalized_title = title.casefold()
    scores = {
        category: sum(normalized_title.count(keyword.casefold()) for keyword in keywords)
        for category, keywords in CATEGORY_KEYWORDS.items()
    }
    best_category = max(CATEGORIES, key=lambda category: scores[category])
    return best_category if scores[best_category] else "개인"


def resolve_category(title: str, requested_category: str) -> str:
    if requested_category == AUTO_CATEGORY:
        return classify_category(title)
    return requested_category


def sanitize_todos(value: Any) -> list[dict[str, Any]]:
    """Return valid, normalized records without duplicate IDs."""
    if not isinstance(value, list):
        return []

    clean: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in value:
        if not isinstance(candidate, dict):
            continue
        todo_id = candidate.get("id")
        title = candidate.get("title")
        category = candidate.get("category")
        completed = candidate.get("completed")
        created_at = candidate.get("createdAt")
        normalized_title = title.strip() if isinstance(title, str) else ""
        if (
            not isinstance(todo_id, str)
            or not todo_id
            or todo_id in seen_ids
            or not normalized_title
            or len(normalized_title) > MAX_TITLE_LENGTH
            or category not in CATEGORIES
            or not isinstance(completed, bool)
            or not is_iso_date(created_at)
        ):
            continue
        seen_ids.add(todo_id)
        clean.append(
            {
                "id": todo_id,
                "title": normalized_title,
                "category": category,
                "completed": completed,
                "createdAt": created_at,
            }
        )
    return clean


def load_todos() -> list[dict[str, Any]]:
    try:
        with DATA_LOCK:
            if not DATA_FILE.exists():
                return []
            return sanitize_todos(json.loads(DATA_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []


def save_todos(todos: list[dict[str, Any]]) -> bool:
    """Persist records using an atomic replace to avoid partial writes."""
    temp_file = DATA_FILE.with_suffix(".tmp")
    try:
        payload = json.dumps(todos, ensure_ascii=False, indent=2)
        with DATA_LOCK:
            temp_file.write_text(payload, encoding="utf-8")
            os.replace(temp_file, DATA_FILE)
        return True
    except OSError:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def set_flash(message: str, icon: str = "✅") -> None:
    st.session_state.flash = (message, icon)


def persist(message: str) -> None:
    if save_todos(st.session_state.todos):
        set_flash(message)
    else:
        set_flash(f"{message} 단, 파일 저장에는 실패했습니다.", "⚠️")


def add_todo() -> None:
    title = st.session_state.new_title.strip()
    requested_category = st.session_state.new_category
    category = resolve_category(title, requested_category)
    if not title:
        st.session_state.add_error = "할 일 제목을 입력해 주세요."
        return
    if len(title) > MAX_TITLE_LENGTH or category not in CATEGORIES:
        st.session_state.add_error = "제목 또는 카테고리를 확인해 주세요."
        return

    st.session_state.todos.insert(
        0,
        {
            "id": str(uuid.uuid4()),
            "title": title,
            "category": category,
            "completed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )
    st.session_state.new_title = ""
    st.session_state.add_error = ""
    if requested_category == AUTO_CATEGORY:
        persist(f"할 일을 추가하고 ‘{category}’로 자동 분류했습니다.")
    else:
        persist("할 일을 추가했습니다.")


def toggle_todo(todo_id: str) -> None:
    for todo in st.session_state.todos:
        if todo["id"] == todo_id:
            todo["completed"] = bool(st.session_state[f"done_{todo_id}"])
            persist("완료 상태를 변경했습니다.")
            return


def start_edit(todo_id: str) -> None:
    todo = next((item for item in st.session_state.todos if item["id"] == todo_id), None)
    if todo is None:
        return
    st.session_state.editing_id = todo_id
    st.session_state[f"edit_title_{todo_id}"] = todo["title"]
    st.session_state[f"edit_category_{todo_id}"] = todo["category"]


def cancel_edit() -> None:
    st.session_state.editing_id = None
    set_flash("수정을 취소했습니다.", "ℹ️")


def save_edit(todo_id: str) -> None:
    title = st.session_state.get(f"edit_title_{todo_id}", "").strip()
    requested_category = st.session_state.get(f"edit_category_{todo_id}")
    category = resolve_category(title, requested_category)
    if not title or len(title) > MAX_TITLE_LENGTH or category not in CATEGORIES:
        set_flash("제목과 카테고리를 확인해 주세요.", "⚠️")
        return

    for todo in st.session_state.todos:
        if todo["id"] == todo_id:
            todo["title"] = title
            todo["category"] = category
            st.session_state.editing_id = None
            if requested_category == AUTO_CATEGORY:
                persist(f"할 일을 수정하고 ‘{category}’로 자동 분류했습니다.")
            else:
                persist("할 일을 수정했습니다.")
            return


def request_delete(todo_id: str) -> None:
    st.session_state.pending_delete = todo_id


def cancel_delete() -> None:
    st.session_state.pending_delete = None


def confirm_delete(todo_id: str) -> None:
    st.session_state.todos = [todo for todo in st.session_state.todos if todo["id"] != todo_id]
    st.session_state.pending_delete = None
    if st.session_state.editing_id == todo_id:
        st.session_state.editing_id = None
    persist("할 일을 삭제했습니다.")


def calculate_progress(todos: list[dict[str, Any]]) -> tuple[int, int, int]:
    total = len(todos)
    completed = sum(todo["completed"] for todo in todos)
    percent = round(completed / total * 100) if total else 0
    return completed, total, percent


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --blue:#0071e3; --ink:#1d1d1f; --gray:#f5f5f7; }
        .stApp { background:#f5f5f7; color:#1d1d1f; }
        [data-testid="stAppViewContainer"] > .main .block-container {
            max-width:980px; padding:1.5rem 1.25rem 5rem;
            font-family:"SF Pro Text","Helvetica Neue",Arial,sans-serif;
        }
        h1, h2, h3, .progress-percent {
            font-family:"SF Pro Display","Helvetica Neue",Arial,sans-serif;
        }
        header[data-testid="stHeader"], footer { visibility:hidden; }
        #MainMenu { visibility:hidden; }
        .hero {
            display:grid; grid-template-columns:1fr .9fr; gap:4rem; align-items:center;
            min-height:390px; padding:3.5rem; border-radius:12px; color:#fff; background:#000;
        }
        .hero-mark, .section-mark, .empty-mark {
            display:grid; place-items:center; width:44px; height:44px; border-radius:50%;
            color:#fff; background:var(--blue); font-size:21px;
        }
        .eyebrow { margin:1rem 0 .5rem; color:#2997ff; font-size:12px; font-weight:600; }
        .hero h1 { margin:0; font-size:clamp(40px,6vw,56px); line-height:1.07; letter-spacing:-.28px; }
        .hero-copy { margin:.9rem 0 0; color:rgba(255,255,255,.75); font-size:17px; line-height:1.47; }
        .progress-card { padding:1.5rem; border-radius:12px; background:#272729; }
        .progress-head { display:flex; justify-content:space-between; gap:1rem; align-items:center; }
        .progress-label { color:#2997ff; font-size:12px; font-weight:600; }
        .progress-title { margin:.3rem 0 0; font-size:21px; }
        .progress-percent { color:#2997ff; font-size:40px; font-weight:600; }
        .progress-track { height:8px; margin:1.5rem 0 .8rem; overflow:hidden; border-radius:999px; background:#424245; }
        .progress-fill { height:100%; border-radius:999px; background:#0071e3; transition:width .3s ease; }
        .progress-meta { display:flex; justify-content:space-between; color:rgba(255,255,255,.68); font-size:12px; }
        .progress-meta strong { color:#fff; }
        .section-title { display:flex; gap:14px; align-items:center; margin:.25rem 0 1rem; }
        .section-title h2 { margin:0; font-size:21px; }
        .section-title p { margin:.25rem 0 0; color:rgba(0,0,0,.65); font-size:14px; }
        div[data-testid="stForm"], .task-section {
            margin-top:1.5rem; padding:2rem; border:0; border-radius:12px; background:#fff;
        }
        div[data-testid="stForm"] { box-shadow:none; }
        [class*="st-key-task_section"] {
            margin-top:1.5rem; padding:2rem; border-radius:12px; background:#e8e8ed;
        }
        .stButton > button, .stFormSubmitButton > button {
            min-height:44px; border-radius:8px; font-weight:400;
        }
        .stFormSubmitButton > button { border-radius:999px; }
        .stFormSubmitButton > button[kind="primary"], .stButton > button[kind="primary"] {
            border-color:#0071e3; color:#fff; background:#0071e3;
        }
        .stButton > button:hover, .stFormSubmitButton > button:hover {
            border-color:#0071e3; color:#0066cc;
        }
        .stFormSubmitButton > button[kind="primary"]:hover,
        .stButton > button[kind="primary"]:hover {
            border-color:#0077ed; color:#fff; background:#0077ed;
        }
        .stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible,
        input:focus-visible, [role="combobox"]:focus-visible,
        [role="radio"]:focus-visible, [role="checkbox"]:focus-visible {
            outline:2px solid #0071e3 !important; outline-offset:2px;
        }
        div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
            min-height:44px; border:0; border-radius:8px; background:#f5f5f7;
        }
        div[role="radiogroup"] { padding:3px; border-radius:11px; background:#fafafc; }
        div[role="radiogroup"] label { min-height:40px; padding:.35rem .8rem; }
        [class*="st-key-task_card_"] {
            margin-top:.65rem; padding:1rem; border-radius:8px; background:#fff;
        }
        [class*="st-key-task_card_completed_"] { background:#fafafc; }
        .task-title { overflow-wrap:anywhere; font-size:17px; font-weight:600; line-height:1.24; }
        [class*="st-key-task_card_completed_"] .task-title {
            color:rgba(0,0,0,.48); text-decoration:line-through;
        }
        .category {
            display:inline-flex; gap:5px; align-items:center; margin-top:7px; padding:3px 9px;
            border-radius:999px; font-size:12px; font-weight:600;
        }
        .category.work, .category.personal, .category.study {
            color:#0066cc; background:#eaf4ff;
        }
        .empty { min-height:220px; display:flex; flex-direction:column; align-items:center;
            justify-content:center; border-radius:8px; background:#fff; text-align:center; }
        .empty h3 { margin:1rem 0 .35rem; font-size:17px; }
        .empty p { margin:0; color:rgba(0,0,0,.7); font-size:14px; }
        @media (max-width:700px) {
            [data-testid="stAppViewContainer"] > .main .block-container { padding:.5rem .5rem 3rem; }
            .hero { grid-template-columns:1fr; gap:2.5rem; min-height:auto; padding:2.5rem 1.5rem; }
            .hero h1 { font-size:40px; }
            div[data-testid="stForm"], [class*="st-key-task_section"] {
                margin-top:.5rem; padding:1.5rem 1.25rem;
            }
            [class*="st-key-task_card_"] { padding:.875rem; }
            [class*="st-key-task_card_"] [data-testid="column"] { min-width:0 !important; }
            [class*="st-key-task_card_"] .stButton > button { width:100%; padding:.35rem .5rem; }
        }
        @media (max-width:360px) {
            .hero { padding:2rem 1.25rem; }
            .hero h1 { font-size:28px; }
            .progress-head { align-items:flex-start; }
            .progress-percent { font-size:34px; }
            div[data-testid="stForm"], [class*="st-key-task_section"] { padding:1.25rem 1rem; }
        }
        @media (prefers-reduced-motion:reduce) { * { transition-duration:.01ms !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(active_filter: str, visible_todos: list[dict[str, Any]]) -> None:
    completed, total, percent = calculate_progress(visible_todos)
    safe_filter = html.escape(active_filter)
    st.markdown(
        f"""
        <section class="hero">
          <div>
            <div class="hero-mark" aria-hidden="true">✓</div>
            <p class="eyebrow">MY TODO</p>
            <h1>{APP_TITLE}</h1>
            <p class="hero-copy">해야 할 일을 가볍게 정리하고,<br>오늘의 흐름에 집중하세요.</p>
          </div>
          <div class="progress-card" aria-label="{safe_filter} 진행률 {percent}퍼센트">
            <div class="progress-head">
              <div><span class="progress-label">TODAY'S PROGRESS</span><h2 class="progress-title">{safe_filter} 진행률</h2></div>
              <strong class="progress-percent">{percent}%</strong>
            </div>
            <div class="progress-track" role="progressbar" aria-label="{safe_filter} 진행률"
                 aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent}">
              <div class="progress-fill" style="width:{percent}%"></div>
            </div>
            <div class="progress-meta"><strong>{completed} / {total} 완료</strong><span>조금씩, 꾸준히</span></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_add_form() -> None:
    with st.form("add_todo", border=True):
        st.markdown(
            """
            <div class="section-title"><div class="section-mark">+</div><div>
            <h2>새 할 일</h2><p>지금 떠오른 일을 바로 기록해 보세요.</p></div></div>
            """,
            unsafe_allow_html=True,
        )
        title_col, category_col = st.columns([3, 1])
        with title_col:
            st.text_input(
                "할 일 제목 *",
                key="new_title",
                max_chars=MAX_TITLE_LENGTH,
                placeholder="무엇을 해야 하나요?",
            )
        with category_col:
            st.selectbox(
                "카테고리",
                CATEGORY_OPTIONS,
                key="new_category",
                help="자동 분류는 제목의 키워드를 분석하며, 일치하는 키워드가 없으면 개인으로 분류합니다.",
            )
        st.caption("자동 분류 예시: ‘회의 자료 준비’ → 업무 · ‘시험 복습’ → 공부 · ‘장보기’ → 개인")
        st.form_submit_button("할 일 추가  ›", type="primary", use_container_width=True, on_click=add_todo)
        if st.session_state.add_error:
            st.error(st.session_state.add_error, icon="⚠️")


def render_edit_form(todo: dict[str, Any]) -> None:
    todo_id = todo["id"]
    st.text_input("할 일 제목", key=f"edit_title_{todo_id}", max_chars=MAX_TITLE_LENGTH)
    st.selectbox("카테고리", CATEGORY_OPTIONS, key=f"edit_category_{todo_id}")
    save_col, cancel_col = st.columns(2)
    save_col.button(
        "저장",
        key=f"save_{todo_id}",
        type="primary",
        use_container_width=True,
        on_click=save_edit,
        args=(todo_id,),
    )
    cancel_col.button("취소", key=f"cancel_edit_{todo_id}", use_container_width=True, on_click=cancel_edit)


def render_todo(todo: dict[str, Any]) -> None:
    todo_id = todo["id"]
    meta = CATEGORY_META[todo["category"]]
    state_name = "completed" if todo["completed"] else "pending"
    with st.container(key=f"task_card_{state_name}_{todo_id}"):
        if st.session_state.editing_id == todo_id:
            render_edit_form(todo)
        else:
            check_col, copy_col, action_col = st.columns([0.38, 4.4, 1.55], vertical_alignment="center")
            with check_col:
                st.checkbox(
                    f"{todo['title']} 완료",
                    value=todo["completed"],
                    key=f"done_{todo_id}",
                    label_visibility="collapsed",
                    on_change=toggle_todo,
                    args=(todo_id,),
                )
            with copy_col:
                safe_title = html.escape(todo["title"])
                safe_category = html.escape(todo["category"])
                st.markdown(
                    f'<div class="task-title">{safe_title}</div>'
                    f'<span class="category {meta["class"]}"><span aria-hidden="true">{meta["icon"]}</span>{safe_category}</span>',
                    unsafe_allow_html=True,
                )
            with action_col:
                edit_col, delete_col = st.columns(2)
                edit_col.button("수정", key=f"edit_{todo_id}", on_click=start_edit, args=(todo_id,))
                delete_col.button("삭제", key=f"delete_{todo_id}", on_click=request_delete, args=(todo_id,))

            if st.session_state.pending_delete == todo_id:
                st.warning(f'“{todo["title"]}” 할 일을 삭제할까요?', icon="⚠️")
                confirm_col, cancel_col = st.columns(2)
                confirm_col.button(
                    "삭제 확인",
                    key=f"confirm_delete_{todo_id}",
                    type="primary",
                    use_container_width=True,
                    on_click=confirm_delete,
                    args=(todo_id,),
                )
                cancel_col.button(
                    "취소",
                    key=f"cancel_delete_{todo_id}",
                    use_container_width=True,
                    on_click=cancel_delete,
                )


def initialize_state() -> None:
    defaults = {
        "todos": load_todos(),
        "active_filter": "전체",
        "editing_id": None,
        "pending_delete": None,
        "new_title": "",
        "new_category": AUTO_CATEGORY,
        "add_error": "",
        "flash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="✓", layout="centered")
    apply_styles()
    initialize_state()

    active_filter = st.session_state.active_filter
    visible_todos = [
        todo for todo in st.session_state.todos
        if active_filter == "전체" or todo["category"] == active_filter
    ]
    render_hero(active_filter, visible_todos)
    render_add_form()

    with st.container(key="task_section"):
        st.markdown("<div class='section-title'><div><p class='eyebrow'>TASKS</p><h2>할 일 목록</h2></div></div>", unsafe_allow_html=True)
        st.radio(
            "카테고리 필터",
            FILTERS,
            horizontal=True,
            key="active_filter",
            label_visibility="collapsed",
        )

        if visible_todos:
            for todo in visible_todos:
                render_todo(todo)
        else:
            has_todos = bool(st.session_state.todos)
            title = "이 카테고리는 비어 있어요" if has_todos else "아직 등록된 할 일이 없어요"
            description = "다른 카테고리를 확인해 보세요." if has_todos else "새로운 할 일을 추가해 보세요."
            st.markdown(
                f'<div class="empty"><div class="empty-mark">✓</div><h3>{title}</h3><p>{description}</p></div>',
                unsafe_allow_html=True,
            )

    if st.session_state.flash:
        message, icon = st.session_state.flash
        st.toast(message, icon=icon)
        st.session_state.flash = None


if __name__ == "__main__":
    main()
