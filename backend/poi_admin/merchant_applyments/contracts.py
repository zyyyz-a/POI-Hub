"""Deterministic validation and official individual-business request mapping."""

import re
from datetime import date
from typing import Any

from .gateway import ApplymentGateway
from .schemas import IndividualFields

REQUIRED_ATTACHMENTS = {
    "license": "营业执照照片",
    "id_front": "身份证人像面",
    "id_back": "身份证国徽面",
    "store_front": "门头照片",
    "store_inside": "店内照片",
    "mini_program_1": "小程序服务页面截图",
}
OPTIONAL_ATTACHMENTS = {
    **{f"mini_program_{i}": f"小程序截图{i}" for i in range(2, 6)},
    **{f"qualification_{i}": f"行业特殊资质{i}" for i in range(1, 6)},
    **{f"supplement_{i}": f"补充材料{i}" for i in range(1, 6)},
}
ATTACHMENT_KINDS = REQUIRED_ATTACHMENTS | OPTIONAL_ATTACHMENTS


def validate_fields(fields: IndividualFields, kinds: set[str]) -> list[str]:
    required = {
        "merchant_name": "执照名称",
        "license_number": "注册号/统一社会信用代码",
        "owner_name": "经营者姓名",
        "id_number": "身份证号码",
        "mobile_phone": "经营者手机",
        "contact_email": "联系邮箱",
        "merchant_shortname": "支付账单商户简称",
        "service_phone": "客服电话",
        "store_name": "门店名称",
        "store_address": "实际经营地址",
        "store_area_code": "经营地址行政区划编码",
        "account_bank": "开户银行",
        "account_number": "结算账号",
        "settlement_id": "结算规则编号",
        "qualification_type": "微信行业名称",
    }
    issues = [f"请填写{label}" for key, label in required.items() if not getattr(fields, key)]
    issues += [f"请上传{label}" for key, label in REQUIRED_ATTACHMENTS.items() if key not in kinds]
    license_number = fields.license_number
    if license_number and not (
        re.fullmatch(r"\d{15}", license_number)
        or re.fullmatch(r"9[0-9A-HJ-NPQRTUWXY]{17}", license_number)
    ):
        issues.append("执照注册号应为15位数字或合法的18位统一社会信用代码")
    if fields.id_number and not re.fullmatch(r"\d{17}[0-9X]", fields.id_number):
        issues.append("身份证号码应为18位，末位字母使用大写X")
    if fields.mobile_phone and not re.fullmatch(r"1\d{10}", fields.mobile_phone):
        issues.append("请填写经营者本人的11位手机号")
    if fields.contact_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields.contact_email):
        issues.append("联系邮箱格式不正确")
    if fields.store_area_code and not re.fullmatch(r"\d{6}", fields.store_area_code):
        issues.append("经营地址行政区划编码应为6位数字")
    if fields.account_number and not re.fullmatch(r"\d{8,32}", fields.account_number):
        issues.append("结算账号应为8至32位数字")
    if not fields.bank_name and not fields.bank_branch_id:
        issues.append("请填写开户支行全称或联行号，供微信核验结算银行")
    if not fields.settlement_rule_confirmed:
        issues.append("请核对官方结算规则和行业资质要求，并勾选确认")
    for prefix, label in (("id", "身份证"), ("license", "营业执照")):
        begin = getattr(fields, f"{prefix}_period_begin")
        end = getattr(fields, f"{prefix}_period_end")
        if prefix == "license" and not begin and not end:
            continue
        try:
            start = date.fromisoformat(begin)
            finish = date.max if end == "长期" else date.fromisoformat(end)
            if start < date(1900, 1, 1) or start > date.today() or finish <= start:
                raise ValueError("invalid interval")
            if finish < date.today():
                raise ValueError("expired")
        except ValueError:
            issues.append(f"请填写有效的{label}起止日期；结束日期可填写“长期”")
    return issues


def build_payload(
    fields: IndividualFields,
    media: dict[str, str],
    business_code: str,
    app_id: str,
    gateway: ApplymentGateway,
) -> dict[str, Any]:
    license_info: dict[str, Any] = {
        "license_copy": media["license"],
        "license_number": fields.license_number,
        "merchant_name": fields.merchant_name,
        "legal_person": fields.owner_name,
    }
    if fields.license_address:
        license_info["license_address"] = fields.license_address
    if fields.license_period_begin:
        license_info.update(
            period_begin=fields.license_period_begin,
            period_end=fields.license_period_end,
        )
    bank: dict[str, Any] = {
        "bank_account_type": (
            "BANK_ACCOUNT_TYPE_PERSONAL"
            if fields.bank_account_type == "personal"
            else "BANK_ACCOUNT_TYPE_CORPORATE"
        ),
        "account_name": gateway.encrypt(
            fields.owner_name if fields.bank_account_type == "personal" else fields.merchant_name
        ),
        "account_bank": fields.account_bank,
        "account_number": gateway.encrypt(fields.account_number),
    }
    for key in ("bank_name", "bank_branch_id"):
        if getattr(fields, key):
            bank[key] = getattr(fields, key)
    settlement: dict[str, Any] = {
        "settlement_id": fields.settlement_id,
        "qualification_type": fields.qualification_type,
    }
    qualification_media = [media[key] for key in sorted(media) if key.startswith("qualification_")]
    if qualification_media:
        settlement["qualifications"] = qualification_media
    payload: dict[str, Any] = {
        "business_code": business_code,
        "contact_info": {
            "contact_type": "LEGAL",
            "contact_name": gateway.encrypt(fields.owner_name),
            "mobile_phone": gateway.encrypt(fields.mobile_phone),
            "contact_email": gateway.encrypt(fields.contact_email),
        },
        "subject_info": {
            "subject_type": "SUBJECT_TYPE_INDIVIDUAL",
            "business_license_info": license_info,
            "identity_info": {
                "id_doc_type": "IDENTIFICATION_TYPE_IDCARD",
                "id_card_info": {
                    "id_card_copy": media["id_front"],
                    "id_card_national": media["id_back"],
                    "id_card_name": gateway.encrypt(fields.owner_name),
                    "id_card_number": gateway.encrypt(fields.id_number),
                    "card_period_begin": fields.id_period_begin,
                    "card_period_end": fields.id_period_end,
                },
            },
        },
        "business_info": {
            "merchant_shortname": fields.merchant_shortname,
            "service_phone": fields.service_phone,
            "sales_info": {
                "sales_scenes_type": ["SALES_SCENES_STORE", "SALES_SCENES_MINI_PROGRAM"],
                "biz_store_info": {
                    "biz_store_name": fields.store_name,
                    "biz_address_code": fields.store_area_code,
                    "biz_store_address": fields.store_address,
                    "store_entrance_pic": [media["store_front"]],
                    "indoor_pic": [media["store_inside"]],
                },
                "mini_program_info": {
                    "mini_program_appid": app_id,
                    "mini_program_pics": [
                        media[key] for key in sorted(media) if key.startswith("mini_program_")
                    ],
                },
            },
        },
        "settlement_info": settlement,
        "bank_account_info": bank,
    }
    supplements = [media[key] for key in sorted(media) if key.startswith("supplement_")]
    if supplements or fields.addition_message:
        payload["addition_info"] = {}
        if supplements:
            payload["addition_info"]["business_addition_pics"] = supplements
        if fields.addition_message:
            payload["addition_info"]["business_addition_msg"] = fields.addition_message
    return payload
