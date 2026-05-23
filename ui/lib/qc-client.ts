// Client-side types only — no server imports.

export interface QCHolding {
  symbol: string;
  quantity: number;
  averagePrice: number;
  marketPrice: number;
  unrealizedPnl: number;
}

export interface QCPortfolio {
  holdings: QCHolding[];
  totalPortfolioValue: number;
  cash: number;
  totalUnrealizedProfit: number;
}

export interface QCOrder {
  id: string;
  symbol: string;
  quantity: number;
  price: number;
  status: string;
  direction: string;
  submittedAt: string;
}

export interface QCLiveStatus {
  status: string;
  projectId: string | null;
  deployId: string | null;
  accountId: string | null;
}

export interface Signal {
  date: string;
  symbol: string;
  score: number;
  rating: string;
}
