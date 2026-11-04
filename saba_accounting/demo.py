from datetime import date
from .jalali import display_jalali


def seed_demo(store):
    """Opt-in demo in a temporary database; never modifies regular user data."""
    if store.companies():
        return
    cid = store.create_company('شرکت نمایشی آفاق')
    fy = store.create_fiscal_year(cid, '۱۴۰۵', '۱۴۰۵/۰۱/۰۱', '۱۴۰۵/۱۲/۲۹')
    a1=store.create_account(cid,'1','دارایی‌ها',1,nature='debit',account_class='asset')
    a2=store.create_account(cid,'11','دارایی‌های جاری',2,nature='debit',parent_id=a1)
    a3=store.create_account(cid,'1101','موجودی نقد',3,nature='debit',parent_id=a2)
    cash=store.create_account(cid,'110101','صندوق دفتر',4,nature='debit',parent_id=a3,is_postable=True)
    a4=store.create_account(cid,'3','حقوق مالکانه',1,nature='credit',account_class='equity')
    a5=store.create_account(cid,'31','سرمایه',2,nature='credit',parent_id=a4)
    a6=store.create_account(cid,'3101','سرمایه مالک',3,nature='credit',parent_id=a5)
    capital=store.create_account(cid,'310101','سرمایه اولیه',4,nature='credit',parent_id=a6,is_postable=True)
    e=store.new_draft(cid,fy,'۱۴۰۵/۰۲/۰۱','سرمایه اولیه',[
         {'account_id':cash,'debit':150_000_000,'credit':0,'narration':'وجه نقد'},
         {'account_id':capital,'debit':0,'credit':150_000_000,'narration':'آورده اولیه'}])
    store.post(cid,e)
    draft=store.new_draft(cid,fy,'۱۴۰۵/۰۲/۰۲','نمونه سند پیش‌نویس',[
        {'account_id':cash,'debit':5_000_000,'credit':0},
        {'account_id':capital,'debit':0,'credit':5_000_000}])

    revenue_root=store.create_account(cid,'4','درآمدها',1,nature='credit',account_class='revenue')
    revenue_k=store.create_account(cid,'41','درآمد عملیاتی',2,nature='credit',parent_id=revenue_root)
    revenue_m=store.create_account(cid,'4101','فروش',3,nature='credit',parent_id=revenue_k)
    revenue=store.create_account(cid,'410101','درآمد فروش',4,nature='credit',parent_id=revenue_m,is_postable=True)
    exp_root=store.create_account(cid,'6','هزینه‌ها',1,nature='debit',account_class='expense')
    exp_k=store.create_account(cid,'61','هزینه عمومی',2,nature='debit',parent_id=exp_root)
    exp_m=store.create_account(cid,'6101','هزینه اداری',3,nature='debit',parent_id=exp_k)
    expense=store.create_account(cid,'610101','هزینه اداری دفتر',4,nature='debit',parent_id=exp_m,is_postable=True)
    sale=store.new_draft(cid,fy,'۱۴۰۵/۰۲/۰۳','فروش خدمات آزمایشی',[
         {'account_id':cash,'debit':25_000_000,'credit':0},
         {'account_id':revenue,'debit':0,'credit':25_000_000}])
    store.post(cid,sale)
    exp=store.new_draft(cid,fy,'۱۴۰۵/۰۲/۰۴','پرداخت هزینه دفتر',[
         {'account_id':expense,'debit':10_000_000,'credit':0},
         {'account_id':cash,'debit':0,'credit':10_000_000}])
    store.post(cid,exp)
