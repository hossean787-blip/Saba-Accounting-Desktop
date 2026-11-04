"""Fictional standalone financial close scenario. Never touches persistent user DB."""

def seed_finance_demo(store):
    if store.companies():return None
    c=store.create_company('شرکت نمونه چرخه مالی')
    y1=store.create_fiscal_year(c,'۱۴۰۵','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
    y2=store.create_fiscal_year(c,'۱۴۰۶','۱۴۰۶/۰۱/۰۱','۱۴۰۶/۱۲/۲۹')
    accounts={}
    for prefix,title,kind,leaves in [
        ('1','دارایی‌ها','asset',[('111101','بانک اصلی')]),
        ('2','بدهی‌ها','liability',[('211101','حساب‌های پرداختنی')]),
        ('3','حقوق مالکانه','equity',[('311101','سرمایه'),('311102','سود و زیان انباشته')]),
        ('4','درآمدها','revenue',[('411101','درآمد فروش')]),
        ('5','بهای تمام‌شده','cost',[('511101','بهای تمام‌شده فروش')]),
        ('6','هزینه‌ها','expense',[('611101','هزینه‌های اداری')])]:
        root=store.create_account(c,prefix,title,1,account_class=kind)
        total=store.create_account(c,prefix+'1','کل '+title,2,parent_id=root)
        sub=store.create_account(c,prefix+'11','معین '+title,3,parent_id=total)
        for code,label in leaves:
            accounts[code]=store.create_account(c,code,label,4,parent_id=sub,is_postable=True)
    detail=store.add_floating_detail(c,'C-001','طرف قرارداد آزمایشی','person')
    store.require_floating_detail(c,accounts['111101'],True)
    docs=[('۱۴۰۵/۰۲/۰۱','ثبت سرمایه',[
         (accounts['111101'],300_000_000,0,detail),(accounts['311101'],0,300_000_000,None)]),
         ('۱۴۰۵/۰۳/۱۱','درآمد فروش',[
         (accounts['111101'],110_000_000,0,detail),(accounts['411101'],0,110_000_000,None)]),
         ('۱۴۰۵/۰۴/۱۰','بهای تمام‌شده',[
         (accounts['511101'],35_000_000,0,None),(accounts['111101'],0,35_000_000,detail)]),
         ('۱۴۰۵/۰۵/۰۷','هزینه اداری',[
         (accounts['611101'],15_000_000,0,None),(accounts['111101'],0,15_000_000,detail)])]
    for date,desc,lines in docs:
        ident=store.new_draft(c,y1,date,desc,[{'account_id':a,'debit':db,'credit':cr,'detail_id':det}
                         for a,db,cr,det in lines])
        store.post(c,ident)
    return {'company_id':c,'current_year':y1,'next_year':y2,'retained_account':accounts['311102'],
            'profit':60_000_000}
