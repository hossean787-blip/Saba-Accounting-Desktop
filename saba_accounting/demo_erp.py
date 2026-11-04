"""Synthetic demonstration records for ERP workflows, never real financial data."""
from .demo import seed_demo


def seed_erp_demo(store):
    if store.companies():return
    seed_demo(store)
    c=store.create_company('آزمایش یکپارچه صبا')
    y=store.create_fiscal_year(c,'۱۴۰۵','۱۴۰۵/۰۱/۰۱','۱۴۰۵/۱۲/۲۹')
    a={}
    groups={
      'asset':('1',['cash','ar','inventory','vat_input','fixed']),
      'liability':('2',['ap','vat_output','payrollpay','deduct','accum']),
      'equity':('3',['capital']),
      'revenue':('4',['sales']),
      'cost':('5',['cogs']),
      'expense':('6',['salaryexp','depexp','projectexp'])}
    for cls,(prefix,names) in groups.items():
        r=store.create_account(c,prefix,cls,1,account_class=cls)
        k=store.create_account(c,prefix+'1',cls,2,parent_id=r)
        m=store.create_account(c,prefix+'101',cls,3,parent_id=k)
        for i,n in enumerate(names,1):
            a[n]=store.create_account(c,prefix+'101'+str(i).zfill(2),n,4,parent_id=m,is_postable=True)
    store.configure(c,cash_account=a['cash'],receivable_account=a['ar'],
        payable_account=a['ap'],inventory_account=a['inventory'],cogs_account=a['cogs'],
        sales_account=a['sales'],vat_input_account=a['vat_input'],vat_output_account=a['vat_output'],
        payroll_expense_account=a['salaryexp'],payroll_payable_account=a['payrollpay'],
        payroll_deduction_account=a['deduct'],depreciation_expense_account=a['depexp'],
        accumulated_depreciation_account=a['accum'],finished_goods_account=a['inventory'])
    supplier=store.create_party(c,'T100','فروشنده نمونه','supplier')
    customer=store.create_party(c,'C100','خریدار نمونه','customer')
    box=store.create_cashbox(c,'بانک نمونه','bank',a['cash'])
    wh=store.create_warehouse(c,'انبار نمونه')
    material=store.create_item(c,'M100','مواد اولیه نمونه','good')
    finished=store.create_item(c,'FG200','محصول ساخته‌شده','good')
    service=store.create_item(c,'SV300','خدمت نمونه','service')
    store.cash_flow(c,y,'۱۴۰۵/۰۲/۰۱',box,'receipt',200_000_000,a['capital'],'SEED-CAP')
    store.invoice(c,y,'۱۴۰۵/۰۲/۰۲','purchase','SEED-P1',supplier,wh,
        [{'item_id':material,'qty':100,'unit_price_rial':100_000,'tax_rate_bps':0}])
    store.bom_add(c,finished,material,2)
    store.produce(c,y,'۱۴۰۵/۰۲/۰۳',finished,20,wh,'SEED-PROD')
    store.invoice(c,y,'۱۴۰۵/۰۲/۰۴','sale','SEED-S1',customer,wh,
        [{'item_id':finished,'qty':4,'unit_price_rial':400_000,'tax_rate_bps':0},
         {'item_id':service,'qty':1,'unit_price_rial':300_000,'tax_rate_bps':0}])
    person=store.create_employee(c,'E100','پرسنل نمونه')
    store.payroll(c,y,'۱۴۰۵/۰۲/۰۵',person,'1405-02',5_000_000,500_000)
    asset=store.create_asset(c,'A100','ماشین‌آلات نمونه',12_000_000,0,12)
    store.depreciate(c,y,'۱۴۰۵/۰۲/۰۵',asset,'1405-02')
    project=store.create_project(c,'PJ100','پروژه نمونه',50_000_000)
    store.project_cost(c,y,'۱۴۰۵/۰۲/۰۵',project,200_000,a['projectexp'],a['ap'])
    store.set_budget(c,y,a['projectexp'],2_000_000)
    return c,y
