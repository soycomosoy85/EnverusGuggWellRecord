"""Date-only values with explicit source precision for partial or invalid dates."""
import re
from datetime import datetime

def source_date(value):
    if value is None or not str(value).strip():return None,None
    text=str(value).strip()
    if isinstance(value,float) and value.is_integer():text=str(int(value))
    try:
        if re.fullmatch(r'\d{4}',text):return datetime(int(text),1,1),dict(raw=str(value),precision='Year')
        if re.fullmatch(r'\d{4}-\d{2}',text):return datetime.fromisoformat(text+'-01'),dict(raw=str(value),precision='Month')
        parsed=datetime.fromisoformat(text.replace('Z','+00:00'));return parsed.replace(hour=0,minute=0,second=0,microsecond=0,tzinfo=None),None
    except (ValueError,TypeError,OverflowError):return None,dict(raw=str(value),precision='Unparsed')
