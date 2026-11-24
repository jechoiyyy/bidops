"""Read-only views of the configured company wiki."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..schemas import company_wiki as dto
from ..services.company_wiki import CompanyWiki, WikiError, read
from ..schemas.wiki_quality import Quality
from ..services.wiki_quality import quality

router = APIRouter(prefix="/api/company-wiki", tags=["company-wiki"])


def _get(view, *args):
    try:
        return read(view, *args)
    except WikiError as exc:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": "회사 위키를 조회할 수 없습니다",
                    "details": None,
                }
            },
        )


@router.get("", response_model=dto.Summary)
def summary():
    return _get(CompanyWiki.summary)


@router.get("/profile", response_model=dto.Profile)
def profile():
    return _get(CompanyWiki.profile)


@router.get("/portfolio", response_model=dto.Portfolio)
def portfolio():
    return _get(CompanyWiki.portfolio)


@router.get("/work-units", response_model=dto.WorkUnits)
def work_units():
    return _get(CompanyWiki.work_units)


@router.get("/pages", response_model=dto.Pages)
def pages():
    return _get(CompanyWiki.pages)


@router.get("/pages/{kind}/{slug:path}", response_model=dto.PageDetail)
def page(kind: str, slug: str):
    return _get(CompanyWiki.page, kind, slug)


@router.get("/work-units/{topic_id}", response_model=dto.Topic)
def topic(topic_id: str):
    return _get(CompanyWiki.topic, topic_id)


@router.get("/portfolio/{project}", response_model=dto.ProjectDetail)
def project_detail(project: str):
    return _get(CompanyWiki.project_detail, project)


@router.get("/portfolio/{project}/requirements/{req_id}", response_model=dto.RequirementDetail)
def requirement(project: str, req_id: str):
    return _get(CompanyWiki.requirement, project, req_id)


@router.get("/quality", response_model=Quality)
def answer_quality():
    return _get(quality)
