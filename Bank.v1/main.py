import os
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db, engine, Base
from models import Account, Transaction

load_dotenv()

# Ensure table schema exists in MySQL
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Super Nova Bank Management System API")

# Setup static and templates
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# --- Pydantic Models ---
class AdminLogin(BaseModel):
    admin_id: str
    admin_password: str

class UserLogin(BaseModel):
    account_no: str
    pin: str

class CreateAccountRequest(BaseModel):
    name: str
    pin: str
    initial_amount: float

class UpdateAccountRequest(BaseModel):
    name: str
    balance: float
    pin_action: str
    new_pin: str = None

class TransactionRequest(BaseModel):
    account_no: str
    amount: float

class ResetPinRequest(BaseModel):
    account_no: str
    current_pin: str
    new_pin: str
    confirm_pin: str


# Helper to get account safely by int ID or raise 404
def get_account_or_404(db: Session, account_no_str: str) -> Account:
    try:
        acc_no = int(account_no_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Account not found")
    account = db.get(Account, acc_no)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


# --- Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/login/admin")
@app.post("/api/admin/login")
def login_admin(req: AdminLogin):
    if req.admin_id == ADMIN_ID and req.admin_password == ADMIN_PASSWORD:
        return {"success": True, "role": "admin"}
    raise HTTPException(status_code=401, detail="Invalid Admin ID or Password.")

@app.post("/api/login/user")
def login_user(req: UserLogin, db: Session = Depends(get_db)):
    try:
        acc_no = int(str(req.account_no).strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Account not found. Please contact administration.")
    
    # ORM query for user account
    stmt = select(Account).where(Account.account_no == acc_no)
    account = db.scalar(stmt)
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found. Please contact administration.")
    if not account.pin_set:
        raise HTTPException(status_code=403, detail="Your PIN has not been set yet. Please contact administration.")
    if str(account.pin).strip() != str(req.pin).strip():
        raise HTTPException(status_code=401, detail="Incorrect PIN. Please try again.")
        
    return {
        "success": True,
        "role": "user",
        "account_no": account.account_no,
        "name": account.name
    }

@app.get("/api/admin/dashboard")
def admin_dashboard(db: Session = Depends(get_db)):
    # ORM aggregation queries for total accounts and sum of balances
    total_accounts = db.scalar(select(func.count(Account.account_no))) or 0
    total_balance = db.scalar(select(func.coalesce(func.sum(Account.balance), 0.0))) or 0.0
    return {"total_accounts": total_accounts, "total_balance": float(total_balance)}

@app.post("/api/admin/accounts")
def create_account(req: CreateAccountRequest, db: Session = Depends(get_db)):
    if len(req.pin) != 4 or not req.pin.isdigit():
        raise HTTPException(status_code=400, detail="PIN must contain exactly 4 numeric digits.")
    
    # ORM instance creation and persist
    new_account = Account(
        name=req.name,
        pin=req.pin,
        balance=Decimal(str(req.initial_amount)),
        pin_set=True
    )
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    
    # Record initial opening deposit transaction if amount > 0
    if req.initial_amount > 0:
        initial_tx = Transaction(
            account_no=new_account.account_no,
            type="OPENING_DEPOSIT",
            amount=Decimal(str(req.initial_amount)),
            balance_after=new_account.balance,
            description="Initial Account Opening Deposit"
        )
        db.add(initial_tx)
        db.commit()

    return {
        "success": True,
        "account_no": new_account.account_no,
        "name": new_account.name,
        "initial_amount": req.initial_amount
    }

@app.get("/api/admin/accounts")
def get_all_accounts(db: Session = Depends(get_db)):
    # ORM query ordered by account_no
    stmt = select(Account).order_by(Account.account_no)
    accounts = db.scalars(stmt).all()
    return {"accounts": [acc.to_dict() for acc in accounts]}

@app.put("/api/admin/accounts/{account_no}")
def update_account(account_no: str, req: UpdateAccountRequest, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_no)
    
    if req.pin_action == "Set new 4-digit PIN directly":
        if not req.new_pin or len(req.new_pin) != 4 or not req.new_pin.isdigit():
            raise HTTPException(status_code=400, detail="New PIN must contain exactly 4 numeric digits.")
        account.pin = req.new_pin
        account.pin_set = True

    account.name = req.name
    account.balance = Decimal(str(req.balance))
    db.commit()
    return {"success": True, "message": "Account updated successfully"}

@app.delete("/api/admin/accounts/{account_no}")
def delete_account(account_no: str, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_no)
    db.delete(account)
    db.commit()
    return {"success": True, "message": "Account deleted successfully"}

@app.get("/api/user/account/{account_no}")
def user_account(account_no: str, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_no)
    return {
        "account": {
            "balance": float(account.balance) if account.balance is not None else 0.0,
            "name": account.name
        }
    }

@app.post("/api/user/deposit")
def deposit(req: TransactionRequest, db: Session = Depends(get_db)):
    account = get_account_or_404(db, req.account_no)
    account.balance = Decimal(str(account.balance or 0.0)) + Decimal(str(req.amount))
    
    # Record deposit transaction entry
    tx = Transaction(
        account_no=account.account_no,
        type="DEPOSIT",
        amount=Decimal(str(req.amount)),
        balance_after=account.balance,
        description="Instant Digital / Cash Deposit"
    )
    db.add(tx)
    db.commit()
    return {"success": True, "message": f"₹{req.amount} deposited successfully."}

@app.post("/api/user/withdraw")
def withdraw(req: TransactionRequest, db: Session = Depends(get_db)):
    account = get_account_or_404(db, req.account_no)
    
    current_balance = float(account.balance or 0.0)
    if req.amount > current_balance:
        raise HTTPException(status_code=400, detail="Insufficient balance.")
        
    account.balance = Decimal(str(current_balance)) - Decimal(str(req.amount))
    
    # Record withdrawal transaction entry
    tx = Transaction(
        account_no=account.account_no,
        type="WITHDRAWAL",
        amount=Decimal(str(req.amount)),
        balance_after=account.balance,
        description="ATM / Branch Cash Withdrawal"
    )
    db.add(tx)
    db.commit()
    return {"success": True, "message": f"₹{req.amount} withdrawn successfully."}

@app.get("/api/user/transactions/{account_no}")
def get_user_transactions(account_no: str, db: Session = Depends(get_db)):
    account = get_account_or_404(db, account_no)
    stmt = select(Transaction).where(Transaction.account_no == account.account_no).order_by(Transaction.id.desc()).limit(25)
    txs = db.scalars(stmt).all()
    return {"transactions": [tx.to_dict() for tx in txs]}

@app.get("/api/admin/transactions")
def get_all_transactions(db: Session = Depends(get_db)):
    stmt = select(Transaction).order_by(Transaction.id.desc()).limit(50)
    txs = db.scalars(stmt).all()
    return {"transactions": [tx.to_dict() for tx in txs]}

@app.put("/api/user/reset_pin")
def reset_pin(req: ResetPinRequest, db: Session = Depends(get_db)):
    if len(req.new_pin) != 4 or not req.new_pin.isdigit():
        raise HTTPException(status_code=400, detail="New PIN must contain exactly 4 numeric digits.")
    if req.new_pin != req.confirm_pin:
        raise HTTPException(status_code=400, detail="New PINs do not match.")
    if req.current_pin == req.new_pin:
        raise HTTPException(status_code=400, detail="New PIN cannot be the same as the current PIN.")
        
    account = get_account_or_404(db, req.account_no)
    if account.pin != req.current_pin:
        raise HTTPException(status_code=401, detail="Current PIN is incorrect.")
        
    account.pin = req.new_pin
    account.pin_set = True
    db.commit()
    return {"success": True, "message": "PIN successfully reset!"}

