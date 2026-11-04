"""Fallback visual shaping for Tk renderers with no Persian bidi support.
Intended for non-editable UI text; values in the database remain normal Unicode.
Pure stdlib, derives Arabic presentation forms from Unicode character database.
"""
import re
import unicodedata

FORMS={}
for point in list(range(0xFB50,0xFE00))+list(range(0xFE70,0xFF00)):
    char=chr(point)
    name=unicodedata.name(char,'')
    if not name.startswith('ARABIC LETTER ') or not name.endswith(' FORM'):
        continue
    norm=unicodedata.normalize('NFKC',char)
    if len(norm)!=1 or not ('\u0600'<=norm<='\u06ff'):
        continue
    for form in ('ISOLATED','INITIAL','MEDIAL','FINAL'):
        if name.endswith(' '+form+' FORM'):
            FORMS.setdefault(norm,{})[form.lower()]=char

RTL_CHARS=set(FORMS)
NUMBERS='0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
MIRROR=str.maketrans('()[]{}<>',')(][}{><')


def visual(text):
    """Convert right-to-left text to LTR-visual glyphs for classic Tk labels.
    Useful on X11. May be disabled on Tk implementations with native bidi.
    """
    text=str(text)
    if not any(c in RTL_CHARS for c in text):
        return text
    shaped=[]
    for i,c in enumerate(text):
        forms=FORMS.get(c)
        if not forms:
            shaped.append(c)
            continue
        prev=FORMS.get(text[i-1],{}) if i>0 else {}
        nxt=FORMS.get(text[i+1],{}) if i+1<len(text) else {}
        join_prev=('final' in forms or 'medial' in forms) and ('initial' in prev or 'medial' in prev)
        join_next=('initial' in forms or 'medial' in forms) and ('final' in nxt or 'medial' in nxt)
        form='medial' if join_prev and join_next else ('final' if join_prev else ('initial' if join_next else 'isolated'))
        shaped.append(forms.get(form,c))
    reversed_text=''.join(shaped[::-1]).translate(MIRROR)
    # Keep number groups and simple ASCII words in forward order after reversing RTL text.
    reversed_text=re.sub(r'[{}][{},./:-]*'.format(NUMBERS,NUMBERS),lambda m:m.group()[::-1],reversed_text)
    reversed_text=re.sub(r'[A-Za-z][A-Za-z0-9_+.-]*',lambda m:m.group()[::-1],reversed_text)
    return reversed_text
