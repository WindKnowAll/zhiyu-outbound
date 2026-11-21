"""从报名后指定的两份 xlsx 读资审场景、话术和追问。

说话以「场景汇总」为关单索引。工作表1是评审稿，不拿来开口。
子表和说明文档里的条数若和主表不一致，保留差异，不改单元格。
话术单元格为空、回答写到一半、或回答自相矛盾时，调用方不得补写。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zhiyu.qualification.xlsx_grid import load_workbook

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "qualification"
RULES_FILE = DATA_DIR / "资审关单场景话术V1.0.xlsx"
QA_FILE = DATA_DIR / "驳回外呼QA.xlsx"

# 说明文档写电话 55、京麦 13。主表实数在 load_catalog().audit 里，以单元格为准。
SOURCE_NOTES = (
    "场景汇总 A2 是关单总原则的采用文本。京麦驳回场景 A2、电话场景 A2 的第2条写成「二次及以上」，与场景汇总「二次，三次及以上」不一致。判定采用场景汇总 A2。",
    "工作表1是评审稿，含建议和状态，不作为开口话术。",
    "电话场景与京麦驳回场景是抽样子表，条数相加不等于场景汇总。",
    "场景汇总第28行和第59行关单方式为电话，但话术单元格为空。不补写。",
    "高频QA 的 C8 先写「是的」，后又写「均无需要加盖」，回答互相矛盾，不引用。",
    "特殊场景 D13 在「如果商标」处断句，不引用这句未完成的回答。",
    "特殊场景 C 列里的「京麦驳回」是关单标记，不是商家问题。",
)


@dataclass(frozen=True)
class Scenario:
    sheet: str
    row: int
    menu: str
    category: str
    reason: str
    close_method: str
    script: str

    @property
    def script_complete(self) -> bool:
        return bool(self.script.strip())


@dataclass(frozen=True)
class Answer:
    sheet: str
    cell: str
    question: str
    answer: str
    usable: bool
    skip_reason: str


@dataclass(frozen=True)
class Catalog:
    scenarios: tuple[Scenario, ...]
    answers: tuple[Answer, ...]
    phone_scripts: int
    qa_labeled: int
    close_principle: str
    audit: dict[str, int | str]


def load_catalog() -> Catalog:
    rules = load_workbook(RULES_FILE)
    qa = load_workbook(QA_FILE)
    summary = rules["场景汇总"]
    scenarios = tuple(_scenarios(summary))
    answers = tuple(_answers(qa))
    phone = sum(1 for item in scenarios if item.close_method == "电话")
    jingmai = sum(1 for item in scenarios if item.close_method == "京麦驳回")
    missing = sum(1 for item in scenarios if not item.script_complete)
    principle = summary.get(2, {}).get(1, "")
    audit: dict[str, int | str] = {
        "场景汇总": len(scenarios),
        "电话": phone,
        "京麦驳回": jingmai,
        "话术为空": missing,
        "京麦驳回场景": _body_rows(rules["京麦驳回场景"]),
        "电话场景": _body_rows(rules["电话场景"]),
        "驳回话术": _qa_scripts(qa),
        "驳回话术有场景标签": _qa_labels(qa),
        "高频QA": sum(1 for item in answers if item.sheet == "高频QA"),
        "特殊场景话术": _special_scripts(qa),
        "特殊场景问题": sum(1 for item in answers if item.sheet == "特殊场景" and item.question),
        "特殊场景京麦标记": _jingmai_marks(qa),
        "采用的关单原则": "场景汇总!A2",
    }
    return Catalog(
        scenarios=scenarios,
        answers=answers,
        phone_scripts=_qa_scripts(qa),
        qa_labeled=_qa_labels(qa),
        close_principle=principle,
        audit=audit,
    )


def scenario_at(catalog: Catalog, row: int) -> Scenario:
    for item in catalog.scenarios:
        if item.row == row:
            return item
    raise KeyError(f"场景汇总没有第 {row} 行")


def _scenarios(grid: dict[int, dict[int, str]]) -> list[Scenario]:
    menu = ""
    category = ""
    found: list[Scenario] = []
    for row in range(13, max(grid) + 1):
        cells = grid.get(row, {})
        if 1 in cells:
            menu = _flat(cells[1])
        if 2 in cells:
            category = _flat(cells[2])
        reason = _flat(cells.get(3, ""))
        method = _flat(cells.get(4, ""))
        if not reason and not method:
            continue
        found.append(
            Scenario(
                sheet="场景汇总",
                row=row,
                menu=menu,
                category=category,
                reason=reason,
                close_method=method,
                script=cells.get(5, "").strip(),
            )
        )
    return found


def _body_rows(grid: dict[int, dict[int, str]]) -> int:
    count = 0
    for row, cells in grid.items():
        if row < 14:
            continue
        if cells.get(3) or cells.get(5):
            count += 1
    return count


def _answers(book: dict[str, dict[int, dict[int, str]]]) -> list[Answer]:
    found: list[Answer] = []
    qa = book["高频QA"]
    for row in range(2, max(qa) + 1):
        cells = qa.get(row, {})
        question = cells.get(2, "").strip()
        answer = cells.get(3, "").strip()
        if not question or not answer:
            continue
        usable, why = _usable_answer(answer, row == 8 and "无需要" in answer and answer.startswith("是的"))
        found.append(Answer("高频QA", f"C{row}", question, answer, usable, why))
    special = book["特殊场景"]
    for row in range(2, max(special) + 1):
        cells = special.get(row, {})
        question = cells.get(3, "").strip()
        answer = cells.get(4, "").strip()
        if not question or question == "京麦驳回":
            continue
        if not answer:
            continue
        usable, why = _usable_answer(answer, False)
        found.append(Answer("特殊场景", f"D{row}", question, answer, usable, why))
    return found


def _usable_answer(answer: str, contradictory: bool) -> tuple[bool, str]:
    if contradictory:
        return False, "回答自相矛盾"
    # 特殊场景 D13 停在「如果商标」，数据说明写明这句没有写完。
    if answer.endswith("如果商标"):
        return False, "回答没有写完"
    return True, ""


def _qa_scripts(book: dict[str, dict[int, dict[int, str]]]) -> int:
    grid = book["驳回话术（开头语+驳回话术+结束语）"]
    return sum(1 for row, cells in grid.items() if row > 1 and cells.get(2))


def _qa_labels(book: dict[str, dict[int, dict[int, str]]]) -> int:
    grid = book["驳回话术（开头语+驳回话术+结束语）"]
    return sum(1 for row, cells in grid.items() if row > 1 and cells.get(1))


def _special_scripts(book: dict[str, dict[int, dict[int, str]]]) -> int:
    grid = book["特殊场景"]
    return sum(1 for row, cells in grid.items() if row > 1 and cells.get(2))


def _jingmai_marks(book: dict[str, dict[int, dict[int, str]]]) -> int:
    grid = book["特殊场景"]
    return sum(1 for row, cells in grid.items() if row > 1 and cells.get(3, "").strip() == "京麦驳回")


def _flat(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())
