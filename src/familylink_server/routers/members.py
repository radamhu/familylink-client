"""Router for the /api/members endpoint."""

from fastapi import APIRouter, Depends

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import FamilyLinkService, get_service

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/members")
async def get_members(
    _email: str = require_user,  # type: ignore[assignment]
    svc: FamilyLinkService = Depends(get_service),  # noqa: B008
) -> list[dict]:
    """Return a JSON list of supervised child members."""
    result = await svc.get_members()
    return [
        {
            "user_id": m.user_id,
            "display_name": m.profile.display_name,
            "email": m.profile.email,
            "is_supervised": bool(
                m.member_supervision_info
                and m.member_supervision_info.is_supervised_member
            ),
        }
        for m in result.members
    ]
