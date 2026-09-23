from sqlalchemy import Column, Integer, String, Numeric, Boolean, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base

class Account(Base):
    """
    SQLAlchemy ORM Model representing the MySQL 'accounts' table.
    """
    __tablename__ = "accounts"

    account_no = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    pin = Column(String(4), nullable=False)
    balance = Column(Numeric(15, 2), default=0.00)
    pin_set = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationship to transactions ledger
    transactions = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="desc(Transaction.id)"
    )

    def to_dict(self):
        """Helper to convert ORM model instance to JSON-serializable dict."""
        return {
            "account_no": self.account_no,
            "name": self.name,
            "balance": float(self.balance) if self.balance is not None else 0.0,
            "pin_set": bool(self.pin_set),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }

class Transaction(Base):
    """
    SQLAlchemy ORM Model representing the MySQL 'transactions' ledger table.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_no = Column(Integer, ForeignKey("accounts.account_no", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)  # 'DEPOSIT', 'WITHDRAWAL', 'OPENING_DEPOSIT'
    amount = Column(Numeric(15, 2), nullable=False)
    balance_after = Column(Numeric(15, 2), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    account = relationship("Account", back_populates="transactions")

    def to_dict(self):
        """Helper to convert Transaction instance to JSON-serializable dict."""
        return {
            "id": self.id,
            "account_no": self.account_no,
            "type": self.type,
            "amount": float(self.amount),
            "balance_after": float(self.balance_after),
            "description": self.description or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
        }

