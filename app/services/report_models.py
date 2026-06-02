from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AllocationItem(BaseModel):
    label: str = Field(min_length=1)
    amount: int = Field(ge=0)
    upside_pct: int = 0
    downside_pct: int = 0
    source: str = ""

    @property
    def net_score(self) -> int:
        return int(self.upside_pct) - int(self.downside_pct)


class AllocationPlan(BaseModel):
    items: list[AllocationItem] = Field(default_factory=list)
    declared_total: int = Field(ge=0)
    deployable: int = Field(ge=0)
    first_tranche: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "AllocationPlan":
        row_total = sum(item.amount for item in self.items)
        if self.declared_total != row_total:
            raise ValueError(
                f"allocation declared_total {self.declared_total} does not match row total {row_total}"
            )
        if self.declared_total > self.deployable:
            raise ValueError(
                f"allocation declared_total {self.declared_total} exceeds deployable {self.deployable}"
            )
        return self


class ReportSection(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""


class ReportContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    generated_at: datetime
    sections: list[ReportSection] = Field(default_factory=list)
    allocation_plan: Optional[AllocationPlan] = None

    @model_validator(mode="after")
    def validate_context(self) -> "ReportContext":
        titles = [section.title for section in self.sections]
        duplicate_titles = sorted({title for title in titles if titles.count(title) > 1})
        if duplicate_titles:
            raise ValueError("duplicate report sections: " + ", ".join(duplicate_titles))
        return self
