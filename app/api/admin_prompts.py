"""
app/api/admin_prompts.py — Admin REST API Endpoints for Prompt Registry & Version Management.

Bảo mật: Yêu cầu Header `X-Admin-Key` khớp với `ADMIN_API_KEY` trong Settings.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.metrics import verify_admin_key
from app.core.prompt_manager import prompt_manager

logger = logging.getLogger("bds.prompts_api")

router = APIRouter(prefix="/api/admin/prompts", tags=["Admin & Prompt Management"])


class CreatePromptRequest(BaseModel):
    prompt_type: str = Field(..., description="Loại prompt: system | synthesize | classify | summarize")
    version: str = Field(..., description="Mã version, ví dụ: v1.1.0, v1.2-concise")
    template: str = Field(..., description="Nội dung template (hỗ trợ placeholder {variable})")
    description: str = Field("", description="Mô tả mục đích và các thay đổi của version này")
    author: str = Field("admin", description="Người tạo/tinh chỉnh prompt")
    set_active: bool = Field(False, description="Kích hoạt ngay version này làm bản chính thức")


class TestRenderRequest(BaseModel):
    prompt_type: str = Field(..., description="system | synthesize | classify | summarize")
    version: Optional[str] = Field(None, description="Version cụ thể (None = lấy active version)")
    variables: dict[str, str] = Field(default_factory=dict, description="Các biến truyền vào template")


@router.get("", summary="Liệt kê toàn bộ Prompt và các phiên bản")
async def list_prompts(
    prompt_type: Optional[str] = Query(None, description="Lọc theo loại prompt (system, synthesize, ...)"),
    _: bool = Security(verify_admin_key),
):
    """Liệt kê danh sách tất cả các phiên bản prompt đã đăng ký."""
    try:
        prompts = await prompt_manager.list_prompts(prompt_type=prompt_type)
        return JSONResponse(content={"status": "success", "count": len(prompts), "data": prompts})
    except Exception as e:
        logger.exception("Failed to list prompts: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active", summary="Lấy danh sách các Version đang Active")
async def get_active_versions(_: bool = Security(verify_admin_key)):
    """Trả về bảng map các version prompt đang chạy thực tế trên production."""
    try:
        active_map = await prompt_manager.get_active_versions_map()
        return JSONResponse(content={"status": "success", "active_versions": active_map})
    except Exception as e:
        logger.exception("Failed to get active prompt versions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_type}/{version}", summary="Xem chi tiết một phiên bản Prompt")
async def get_prompt_detail(
    prompt_type: str,
    version: str,
    _: bool = Security(verify_admin_key),
):
    """Xem đầy đủ nội dung template và metadata của một phiên bản cụ thể."""
    try:
        detail = await prompt_manager.get_prompt_detail(prompt_type=prompt_type, version=version)
        if not detail:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prompt '{prompt_type}' version '{version}' not found",
            )
        return JSONResponse(content={"status": "success", "data": detail})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get prompt detail: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="Tạo mới một phiên bản Prompt")
async def create_prompt_version(
    payload: CreatePromptRequest,
    _: bool = Security(verify_admin_key),
):
    """Tạo một phiên bản prompt mới (hỗ trợ test A/B hoặc cập nhật quy tắc tư vấn)."""
    try:
        res = await prompt_manager.create_prompt_version(
            prompt_type=payload.prompt_type,
            version=payload.version,
            template=payload.template,
            description=payload.description,
            author=payload.author,
            set_active=payload.set_active,
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"status": "created", "data": res},
        )
    except Exception as e:
        logger.exception("Failed to create prompt version: %s", e)
        raise HTTPException(status_code=400, detail=f"Cannot create prompt: {str(e)}")


@router.post("/{prompt_type}/{version}/activate", summary="Kích hoạt một phiên bản Prompt (Atomic Switch)")
async def activate_prompt_version(
    prompt_type: str,
    version: str,
    _: bool = Security(verify_admin_key),
):
    """Chuyển đổi tức thì phiên bản prompt đang chạy trên live mà không cần restart server."""
    try:
        success = await prompt_manager.activate_version(prompt_type=prompt_type, version=version)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prompt '{prompt_type}' version '{version}' not found",
            )
        return JSONResponse(
            content={
                "status": "activated",
                "message": f"Successfully activated {prompt_type} -> {version}",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to activate prompt version: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-render", summary="Thử nghiệm render template prompt")
async def test_render_prompt(
    payload: TestRenderRequest,
    _: bool = Security(verify_admin_key),
):
    """Thử render template với các biến mẫu để kiểm tra lỗi format trước khi deploy."""
    try:
        if payload.version:
            detail = await prompt_manager.get_prompt_detail(payload.prompt_type, payload.version)
            if not detail:
                raise HTTPException(status_code=404, detail="Prompt version not found")
            template = detail["template"]
            version_used = payload.version
        else:
            template, version_used = await prompt_manager.get_active_prompt(payload.prompt_type)

        try:
            rendered = template.format(**payload.variables)
        except KeyError as ke:
            raise HTTPException(
                status_code=400,
                detail=f"Missing variable {ke} required by prompt template",
            )

        return JSONResponse(
            content={
                "status": "success",
                "prompt_type": payload.prompt_type,
                "version_used": version_used,
                "rendered_text": rendered,
                "char_count": len(rendered),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to test render prompt: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
