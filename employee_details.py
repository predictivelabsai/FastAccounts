"""Validation for optional employee contact and payment details."""
import re
from datetime import date


class EmployeeDetailsError(ValueError):
    """An employee detail could not be validated."""


def validate_details(data):
    for field, maximum in (('phone', 50), ('bank_account_owner', 180), ('address', 2000)):
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise EmployeeDetailsError('Employee contact details exceed the allowed length')
        data[field] = value.strip() or None if value else None
    iban = data.get('iban')
    if iban:
        if not isinstance(iban, str):
            raise EmployeeDetailsError('Enter an IBAN with a valid ISO 13616 checksum')
        iban = re.sub(r'\s+', '', iban).upper()
        if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}', iban):
            raise EmployeeDetailsError('Enter an IBAN with a valid ISO 13616 checksum')
        digits = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in iban[4:] + iban[:4])
        if int(digits) % 97 != 1:
            raise EmployeeDetailsError('Enter an IBAN with a valid ISO 13616 checksum')
    data['iban'] = iban or None
    dob = data.get('date_of_birth')
    if dob:
        try:
            parsed = date.fromisoformat(dob)
            if parsed.isoformat() != dob:
                raise ValueError()
        except (ValueError, TypeError):
            raise EmployeeDetailsError('Date of birth must be a valid date in YYYY-MM-DD format') from None
        data['date_of_birth'] = parsed.isoformat()
    else:
        data['date_of_birth'] = birth_date_from_personal_code(data.get('personal_id'))
    return data


def birth_date_from_personal_code(value):
    """Derive the date from an Estonian personal code when its date is valid."""
    if not isinstance(value, str) or not re.fullmatch(r'[1-8][0-9]{10}', value):
        return None
    try:
        century = 1800 + ((int(value[0]) - 1) // 2) * 100
        return date(century + int(value[1:3]), int(value[3:5]), int(value[5:7])).isoformat()
    except ValueError:
        return None
