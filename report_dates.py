from datetime import date, datetime

def date_columns(headers):
    return {i for i, h in enumerate(headers) if str(h).strip().lower().startswith("tanggal")}

def report_date(value, display=False):
    if value is None or value == "":
        return value
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                value = datetime.strptime(str(value), fmt).date()
                break
            except ValueError:
                continue
        else:
            return value
    return value.strftime("%d-%m-%Y") if display else value
