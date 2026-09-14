"""Stateful onboarding rules that never manufacture official approval."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from poi_admin.connections.models import WeChatConnection
from poi_admin.connections.ports import Capability
from poi_admin.stores.models import ServicePoi, Store

from .models import (
    MerchantMiniProgram,
    MerchantOnboardingCase,
    MiniProgramStoreBinding,
    PlatformMiniProgram,
    PositionServiceMount,
    utcnow,
)

DEFAULT_REQUIREMENTS: tuple[dict[str, Any], ...] = (
    {
        "code": "official_category_open",
        "label": "官方当前开放该类目和地区",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "region_supported",
        "label": "经营地区在当前开放范围内",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "business_license",
        "label": "营业执照真实有效",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "merchant_admin_confirmed",
        "label": "商家超级管理员本人确认",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "storefront_photo",
        "label": "真实清晰门头照片",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "interior_photo",
        "label": "真实店内环境照片",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "public_phone",
        "label": "可公开且能接审核电话的门店号码",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "map_location",
        "label": "腾讯地图点位真实且落点正确",
        "required": True,
        "present": False,
        "verified": False,
    },
    {
        "code": "settlement_account",
        "label": "结算账户与商户主体匹配",
        "required": True,
        "present": False,
        "verified": False,
    },
)


class OnboardingError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class OnboardingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_cases(self, tenant_id: str) -> list[MerchantOnboardingCase]:
        rows = await self.session.execute(
            select(MerchantOnboardingCase)
            .where(MerchantOnboardingCase.tenant_id == tenant_id)
            .order_by(MerchantOnboardingCase.updated_at.desc(), MerchantOnboardingCase.id)
        )
        return list(rows.scalars().all())

    async def get_case(self, tenant_id: str, case_id: str) -> MerchantOnboardingCase:
        row = (
            await self.session.execute(
                select(MerchantOnboardingCase).where(
                    MerchantOnboardingCase.tenant_id == tenant_id,
                    MerchantOnboardingCase.id == case_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise OnboardingError("onboarding_case_not_found", "准入工单不存在", 404)
        return row

    async def create_case(
        self, tenant_id: str, actor_user_id: str, values: dict[str, Any]
    ) -> MerchantOnboardingCase:
        store_id = str(values["store_id"])
        if not await self._store_exists(tenant_id, store_id):
            raise OnboardingError("store_not_found", "门店不存在", 404)
        requirements = values.pop("requirements", None) or [
            dict(item) for item in DEFAULT_REQUIREMENTS
        ]
        row = MerchantOnboardingCase(
            tenant_id=tenant_id,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            requirements=requirements,
            next_action="完成类目开放、地区、主体、门店和结算资料预审",
            **values,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError(
                "onboarding_case_exists", "该门店、路线和类目已有准入工单", 409
            ) from error
        await self.session.refresh(row)
        return row

    async def run_precheck(
        self,
        tenant_id: str,
        case_id: str,
        actor_user_id: str,
        items: list[dict[str, Any]],
        rule_source_reference: str,
    ) -> MerchantOnboardingCase:
        row = await self.get_case(tenant_id, case_id)
        today = date.today()
        failures: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for item in items:
            item = dict(item)
            code = str(item["code"])
            if code in seen:
                raise OnboardingError("duplicate_requirement", f"预审项重复：{code}")
            seen.add(code)
            if item.get("required") and not item.get("present"):
                failures.append({"code": code, "reason": "缺少必需资料或资格"})
            elif item.get("required") and not item.get("verified"):
                failures.append({"code": code, "reason": "必需项尚未核验"})
            expires_on = item.get("expires_on")
            parsed_expiry = (
                date.fromisoformat(expires_on) if isinstance(expires_on, str) else expires_on
            )
            if parsed_expiry and parsed_expiry < today:
                failures.append({"code": code, "reason": "资料已过期"})
            elif not item.get("required") and not item.get("verified"):
                warnings.append({"code": code, "reason": "非必需项尚未核验"})
            if isinstance(expires_on, date):
                item["expires_on"] = expires_on.isoformat()
            normalized.append(item)
        mandatory_codes = {"official_category_open", "region_supported"}
        missing_controls = mandatory_codes - seen
        for code in sorted(missing_controls):
            failures.append({"code": code, "reason": "缺少平台开放性核验项"})

        row.requirements = normalized
        row.precheck_report = {
            "evaluated_at": utcnow().isoformat(),
            "rule_source_reference": rule_source_reference,
            "failures": failures,
            "warnings": warnings,
            "item_count": len(normalized),
        }
        row.updated_by_user_id = actor_user_id
        row.version += 1
        if failures:
            row.precheck_status = "failed"
            row.stage = "precheck"
            row.status = "blocked"
            row.blocker_code = "precheck_failed"
            row.blocker_message = f"预审存在 {len(failures)} 个阻塞项"
            row.next_action = "补齐资料并重新执行预审；不得提交官方报备"
        else:
            row.precheck_status = "passed"
            row.stage = "official_filing"
            row.status = "in_progress"
            row.blocker_code = None
            row.blocker_message = None
            row.next_action = "通过官方入口或经核验的授权渠道提交报备"
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def record_official_submission(
        self,
        tenant_id: str,
        case_id: str,
        actor_user_id: str,
        official_reference: str,
        evidence_reference: str,
    ) -> MerchantOnboardingCase:
        row = await self.get_case(tenant_id, case_id)
        if row.precheck_status != "passed":
            raise OnboardingError("precheck_required", "预审未通过，不能记录官方报备")
        row.official_status = "under_review"
        row.official_reference = official_reference
        row.official_evidence_reference = evidence_reference
        row.official_submitted_at = utcnow()
        row.official_decided_at = None
        row.stage = "official_filing"
        row.status = "in_progress"
        row.blocker_code = None
        row.blocker_message = None
        row.next_action = "等待官方审核；收到结果后上传官方凭证"
        row.updated_by_user_id = actor_user_id
        row.version += 1
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def record_official_decision(
        self,
        tenant_id: str,
        case_id: str,
        actor_user_id: str,
        decision: str,
        evidence_reference: str,
        message: str | None,
    ) -> MerchantOnboardingCase:
        row = await self.get_case(tenant_id, case_id)
        if not row.official_reference or row.official_status == "not_submitted":
            raise OnboardingError("official_submission_required", "尚未记录官方报备")
        if not evidence_reference.strip():
            raise OnboardingError("official_evidence_required", "必须保存可核验的官方结果凭证")
        row.official_status = decision
        row.official_evidence_reference = evidence_reference
        row.official_decided_at = utcnow()
        row.updated_by_user_id = actor_user_id
        row.version += 1
        if decision == "approved":
            row.stage = "position_authorization"
            row.status = "in_progress"
            row.blocker_code = None
            row.blocker_message = None
            row.next_action = "配置商家小程序、微信位置服务定义并申请门店挂载"
        elif decision == "needs_more_info":
            row.stage = "official_filing"
            row.status = "blocked"
            row.blocker_code = "official_needs_more_info"
            row.blocker_message = message or "官方要求补充材料"
            row.next_action = "仅按官方缺项补件，保留原报备编号"
        else:
            row.stage = "official_filing"
            row.status = "blocked" if decision == "paused" else "rejected"
            row.blocker_code = f"official_{decision}"
            row.blocker_message = message or (
                "官方当前暂停受理" if decision == "paused" else "官方报备未通过"
            )
            row.next_action = "停止真实上线，按官方结果等待或整改；不得绕过审批"
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_mini_programs(self, tenant_id: str) -> list[MerchantMiniProgram]:
        rows = await self.session.execute(
            select(MerchantMiniProgram)
            .where(MerchantMiniProgram.tenant_id == tenant_id)
            .order_by(MerchantMiniProgram.updated_at.desc(), MerchantMiniProgram.id)
        )
        return list(rows.scalars().all())

    async def get_mini_program(self, tenant_id: str, app_id: str) -> MerchantMiniProgram:
        row = (
            await self.session.execute(
                select(MerchantMiniProgram).where(
                    MerchantMiniProgram.tenant_id == tenant_id,
                    MerchantMiniProgram.id == app_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise OnboardingError("mini_program_not_found", "小程序登记不存在", 404)
        return row

    async def create_mini_program(
        self, tenant_id: str, actor_user_id: str, values: dict[str, Any]
    ) -> MerchantMiniProgram:
        connection = await self._validate_commerce_connection(
            tenant_id, values.get("connection_id")
        )
        self._validate_app_payment_ownership(values, connection)
        if values.get("payment_owner_verified") and not values.get("payment_merchant_id"):
            raise OnboardingError("payment_merchant_required", "核验支付归属前必须填写商户号")
        row = MerchantMiniProgram(
            tenant_id=tenant_id,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            **values,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError("mini_program_exists", "该 AppID 已登记", 409) from error
        await self.session.refresh(row)
        return row

    async def update_mini_program(
        self,
        tenant_id: str,
        app_id: str,
        actor_user_id: str,
        version: int,
        changes: dict[str, Any],
    ) -> MerchantMiniProgram:
        row = await self.get_mini_program(tenant_id, app_id)
        if row.version != version:
            raise OnboardingError("version_conflict", "小程序登记已被他人修改，请刷新", 409)
        for key, value in changes.items():
            setattr(row, key, value)
        connection = await self._validate_commerce_connection(tenant_id, row.connection_id)
        self._validate_app_payment_ownership(
            {"app_id": row.app_id, "payment_merchant_id": row.payment_merchant_id},
            connection,
        )
        if row.payment_owner_verified and not row.payment_merchant_id:
            raise OnboardingError("payment_merchant_required", "核验支付归属前必须填写商户号")
        if row.status == "active":
            missing = []
            if not row.connection_id:
                missing.append("独立小程序交易连接")
            if not row.app_id:
                missing.append("AppID")
            if not row.authorization_reference:
                missing.append("商家授权凭证")
            if not row.payment_owner_verified:
                missing.append("商户号归属核验")
            if not row.callback_configured:
                missing.append("支付/业务回调")
            if missing:
                raise OnboardingError(
                    "mini_program_not_ready", "小程序不能启用，缺少：" + "、".join(missing)
                )
        row.updated_by_user_id = actor_user_id
        row.version += 1
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError("mini_program_exists", "该 AppID 已登记", 409) from error
        await self.session.refresh(row)
        return row

    async def list_platform_mini_programs(self) -> list[PlatformMiniProgram]:
        rows = await self.session.execute(
            select(PlatformMiniProgram).order_by(
                PlatformMiniProgram.updated_at.desc(), PlatformMiniProgram.id
            )
        )
        return list(rows.scalars().all())

    async def get_platform_mini_program(self, program_id: str) -> PlatformMiniProgram:
        row = await self.session.scalar(
            select(PlatformMiniProgram).where(PlatformMiniProgram.id == program_id)
        )
        if row is None:
            raise OnboardingError("platform_mini_program_not_found", "平台小程序不存在", 404)
        return row

    async def create_platform_mini_program(
        self, actor_user_id: str, values: dict[str, Any]
    ) -> PlatformMiniProgram:
        await self._validate_platform_connection(values.get("connection_id"))
        row = PlatformMiniProgram(
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            **values,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError("platform_app_id_exists", "该平台 AppID 已登记", 409) from error
        await self.session.refresh(row)
        return row

    async def update_platform_mini_program(
        self,
        program_id: str,
        actor_user_id: str,
        version: int,
        changes: dict[str, Any],
    ) -> PlatformMiniProgram:
        row = await self.get_platform_mini_program(program_id)
        if row.version != version:
            raise OnboardingError("version_conflict", "平台小程序已被他人修改，请刷新", 409)
        if "connection_id" in changes:
            await self._validate_platform_connection(changes.get("connection_id"))
        for key, value in changes.items():
            setattr(row, key, value)
        if row.status == "active":
            missing = []
            if not row.connection_id:
                missing.append("平台小程序交易连接")
            if not row.app_id:
                missing.append("AppID")
            if not row.callback_configured:
                missing.append("支付回调")
            if missing:
                raise OnboardingError(
                    "platform_mini_program_not_ready",
                    "平台小程序不能启用，缺少：" + "、".join(missing),
                )
        row.updated_by_user_id = actor_user_id
        row.version += 1
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError("platform_app_id_exists", "该平台 AppID 已登记", 409) from error
        await self.session.refresh(row)
        return row

    async def list_bindings(self, tenant_id: str) -> list[MiniProgramStoreBinding]:
        rows = await self.session.execute(
            select(MiniProgramStoreBinding)
            .where(MiniProgramStoreBinding.tenant_id == tenant_id)
            .order_by(MiniProgramStoreBinding.updated_at.desc(), MiniProgramStoreBinding.id)
        )
        return list(rows.scalars().all())

    async def get_binding(self, tenant_id: str, binding_id: str) -> MiniProgramStoreBinding:
        row = await self.session.scalar(
            select(MiniProgramStoreBinding).where(
                MiniProgramStoreBinding.tenant_id == tenant_id,
                MiniProgramStoreBinding.id == binding_id,
            )
        )
        if row is None:
            raise OnboardingError("store_binding_not_found", "门店入口绑定不存在", 404)
        return row

    async def create_binding(
        self, tenant_id: str, actor_user_id: str, values: dict[str, Any]
    ) -> MiniProgramStoreBinding:
        await self.get_platform_mini_program(str(values["platform_mini_program_id"]))
        store_id = str(values["store_id"])
        if not await self._store_exists(tenant_id, store_id):
            raise OnboardingError("store_not_found", "门店不存在", 404)
        row = MiniProgramStoreBinding(
            tenant_id=tenant_id,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            **values,
        )
        self._ensure_binding_ready(row)
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError(
                "store_binding_exists", "该门店或入口编码已绑定平台小程序", 409
            ) from error
        await self.session.refresh(row)
        return row

    async def update_binding(
        self,
        tenant_id: str,
        binding_id: str,
        actor_user_id: str,
        version: int,
        changes: dict[str, Any],
    ) -> MiniProgramStoreBinding:
        row = await self.get_binding(tenant_id, binding_id)
        if row.version != version:
            raise OnboardingError("version_conflict", "门店入口绑定已被他人修改，请刷新", 409)
        for key, value in changes.items():
            setattr(row, key, value)
        self._ensure_binding_ready(row)
        row.updated_by_user_id = actor_user_id
        row.version += 1
        await self.session.commit()
        await self.session.refresh(row)
        return row

    @staticmethod
    def _ensure_binding_ready(row: MiniProgramStoreBinding) -> None:
        if row.status != "active":
            return
        missing = []
        if not row.tencent_poi_id:
            missing.append("腾讯地图 POI 标识")
        if not row.official_reference:
            missing.append("官方审核编号")
        if not row.evidence_reference:
            missing.append("官方审核凭证")
        if missing:
            raise OnboardingError(
                "store_binding_not_ready", "门店入口不能启用，缺少：" + "、".join(missing)
            )

    async def list_mounts(self, tenant_id: str) -> list[PositionServiceMount]:
        rows = await self.session.execute(
            select(PositionServiceMount)
            .where(PositionServiceMount.tenant_id == tenant_id)
            .order_by(PositionServiceMount.updated_at.desc(), PositionServiceMount.id)
        )
        return list(rows.scalars().all())

    async def get_mount(self, tenant_id: str, mount_id: str) -> PositionServiceMount:
        row = (
            await self.session.execute(
                select(PositionServiceMount).where(
                    PositionServiceMount.tenant_id == tenant_id,
                    PositionServiceMount.id == mount_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise OnboardingError("position_service_not_found", "位置服务不存在", 404)
        return row

    async def create_mount(
        self, tenant_id: str, actor_user_id: str, values: dict[str, Any]
    ) -> PositionServiceMount:
        case = await self.get_case(tenant_id, str(values["onboarding_case_id"]))
        store_id = str(values["store_id"])
        if case.store_id != store_id or not await self._store_exists(tenant_id, store_id):
            raise OnboardingError("onboarding_store_mismatch", "准入工单与门店不匹配")
        if case.precheck_status != "passed":
            raise OnboardingError("precheck_required", "预审通过后才能配置位置服务")
        await self.get_mini_program(tenant_id, str(values["mini_program_id"]))
        service_poi_id = values.get("service_poi_id")
        if service_poi_id and not await self._poi_exists(tenant_id, str(service_poi_id)):
            raise OnboardingError("poi_not_found", "服务 POI 不存在", 404)
        row = PositionServiceMount(
            tenant_id=tenant_id,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            **values,
        )
        self.session.add(row)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise OnboardingError("position_service_exists", "该门店服务已经登记", 409) from error
        await self.session.refresh(row)
        return row

    async def transition_mount(
        self,
        tenant_id: str,
        mount_id: str,
        actor_user_id: str,
        version: int,
        target: str,
        official_reference: str | None,
        evidence_reference: str | None,
        message: str | None,
    ) -> PositionServiceMount:
        row = await self.get_mount(tenant_id, mount_id)
        if row.version != version:
            raise OnboardingError("version_conflict", "位置服务已被他人修改，请刷新", 409)
        allowed: dict[str, set[str]] = {
            "draft": {"service_defined", "rejected"},
            "service_defined": {"authorization_pending", "rejected"},
            "authorization_pending": {"authorized", "rejected"},
            "authorized": {"mounted", "unmounted", "rejected"},
            "mounted": {"unmounted"},
            "unmounted": {"authorization_pending", "mounted"},
            "rejected": {"authorization_pending"},
        }
        if target not in allowed.get(row.status, set()):
            raise OnboardingError(
                "invalid_position_transition", f"不能从 {row.status} 变更为 {target}", 409
            )
        case = await self.get_case(tenant_id, row.onboarding_case_id)
        app = await self.get_mini_program(tenant_id, row.mini_program_id)
        if target in {"authorization_pending", "authorized", "mounted"}:
            if case.official_status != "approved":
                raise OnboardingError("official_approval_required", "官方报备未通过，不能申请挂载")
        if target in {"authorized", "mounted"}:
            if not official_reference or not evidence_reference:
                raise OnboardingError(
                    "position_evidence_required", "官方授权编号和结果凭证缺一不可"
                )
        if target == "mounted":
            missing = []
            if row.service_poi_id is None:
                missing.append("审核通过的服务 POI")
            if app.status not in {"authorized", "active"}:
                missing.append("已授权小程序")
            if app.location_service_status != "authorized":
                missing.append("小程序位置服务授权")
            if missing:
                raise OnboardingError(
                    "position_mount_not_ready", "不能挂载，缺少：" + "、".join(missing)
                )
        row.status = target
        row.official_reference = official_reference or row.official_reference
        row.evidence_reference = evidence_reference or row.evidence_reference
        row.last_error = message if target == "rejected" else None
        row.updated_by_user_id = actor_user_id
        row.version += 1
        if target == "authorized":
            row.authorized_at = utcnow()
        if target == "mounted":
            row.mounted_at = utcnow()
        case.position_status = target
        case.updated_by_user_id = actor_user_id
        case.version += 1
        if target == "mounted":
            case.stage = "ready"
            case.status = "ready"
            case.next_action = "完成商品、支付、预约、核销和退款闭环测试"
        elif target == "rejected":
            case.status = "blocked"
            case.blocker_code = "position_service_rejected"
            case.blocker_message = message or "位置服务授权未通过"
            case.next_action = "按官方驳回原因整改后重新申请"
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def readiness(self, tenant_id: str, case_id: str) -> dict[str, Any]:
        case = await self.get_case(tenant_id, case_id)
        mounts = list(
            (
                await self.session.execute(
                    select(PositionServiceMount).where(
                        PositionServiceMount.tenant_id == tenant_id,
                        PositionServiceMount.onboarding_case_id == case.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        mounted = [item for item in mounts if item.status == "mounted"]
        apps: list[MerchantMiniProgram] = []
        for mount in mounted:
            apps.append(await self.get_mini_program(tenant_id, mount.mini_program_id))
        checks = {
            "precheck_passed": case.precheck_status == "passed",
            "official_approved": case.official_status == "approved",
            "position_service_mounted": bool(mounted),
            "mini_program_ready": any(app.status == "active" for app in apps),
            "merchant_payment_verified": any(app.payment_owner_verified for app in apps),
            "callback_configured": any(app.callback_configured for app in apps),
        }
        labels = {
            "precheck_passed": "类目和资料预审未通过",
            "official_approved": "官方报备未通过",
            "position_service_mounted": "微信位置服务尚未挂载",
            "mini_program_ready": "商家小程序尚未启用",
            "merchant_payment_verified": "商家支付商户号归属未核验",
            "callback_configured": "支付或业务回调尚未配置",
        }
        blockers = [labels[key] for key, passed in checks.items() if not passed]
        return {"case_id": case.id, "ready": not blockers, "blockers": blockers, "checks": checks}

    async def _store_exists(self, tenant_id: str, store_id: str) -> bool:
        return (
            await self.session.scalar(
                select(Store.id).where(Store.tenant_id == tenant_id, Store.id == store_id)
            )
            is not None
        )

    async def _poi_exists(self, tenant_id: str, poi_id: str) -> bool:
        return (
            await self.session.scalar(
                select(ServicePoi.id).where(
                    ServicePoi.tenant_id == tenant_id, ServicePoi.id == poi_id
                )
            )
            is not None
        )

    async def _validate_commerce_connection(
        self, tenant_id: str, connection_id: object
    ) -> WeChatConnection | None:
        if connection_id in {None, ""}:
            return None
        connection = (
            await self.session.execute(
                select(WeChatConnection).where(
                    WeChatConnection.tenant_id == tenant_id,
                    WeChatConnection.id == str(connection_id),
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise OnboardingError("connection_not_found", "小程序交易连接不存在", 404)
        if connection.capability != Capability.MINI_PROGRAM_COMMERCE.value:
            raise OnboardingError("invalid_connection_capability", "必须选择独立小程序交易连接")
        return connection

    async def _validate_platform_connection(
        self, connection_id: object
    ) -> WeChatConnection | None:
        if connection_id in {None, ""}:
            return None
        connection = await self.session.scalar(
            select(WeChatConnection).where(WeChatConnection.id == str(connection_id))
        )
        if connection is None:
            raise OnboardingError("connection_not_found", "平台小程序交易连接不存在", 404)
        if connection.capability != Capability.MINI_PROGRAM_COMMERCE.value:
            raise OnboardingError("invalid_connection_capability", "必须选择独立小程序交易连接")
        return connection

    @staticmethod
    def _validate_app_payment_ownership(
        values: dict[str, Any], connection: WeChatConnection | None
    ) -> None:
        if connection is None:
            return
        app_id = values.get("app_id")
        merchant_id = values.get("payment_merchant_id")
        if connection.app_id and app_id and connection.app_id != app_id:
            raise OnboardingError(
                "mini_program_appid_mismatch", "小程序登记 AppID 与交易连接不一致"
            )
        if connection.merchant_id and merchant_id and connection.merchant_id != merchant_id:
            raise OnboardingError("payment_merchant_mismatch", "小程序登记商户号与交易连接不一致")


__all__ = ["DEFAULT_REQUIREMENTS", "OnboardingError", "OnboardingService"]
