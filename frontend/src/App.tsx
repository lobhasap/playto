import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

type Merchant = { id: number; name: string; email: string };
type Dashboard = {
    merchant_id: number;
    available_balance_paise: number;
    held_balance_paise: number;
    recent_ledger: Array<{ id: number; entry_type: string; amount_paise: number; created_at: string }>;
    payouts: Array<{ id: string; amount_paise: number; status: string; failure_reason: string; attempts: number; created_at: string }>;
};
const API_BASE = "http://127.0.0.1:8000/api/v1";

const inr = (paise: number) => `Rs. ${(paise / 100).toFixed(2)}`;

export function App() {
    const [merchants, setMerchants] = useState<Merchant[]>([]);
    const [selectedMerchantId, setSelectedMerchantId] = useState<number | null>(null);
    const [dashboard, setDashboard] = useState<Dashboard | null>(null);
    const [amount, setAmount] = useState("1000");
    const [bankId, setBankId] = useState("1");
    const [error, setError] = useState("");

    const merchantOptions = useMemo(() => merchants.map((m) => ({ label: m.name, value: m.id })), [merchants]);

    const fetchDashboard = async (merchantId: number) => {
        const res = await fetch(`${API_BASE}/merchants/${merchantId}/dashboard`);
        if (res.ok) {
            setDashboard(await res.json());
        }
    };

    useEffect(() => {
        const boot = async () => {
            const res = await fetch(`${API_BASE}/merchants`);
            const data = (await res.json()) as Merchant[];
            setMerchants(data);
            if (data.length > 0) {
                setSelectedMerchantId(data[0].id);
                setBankId(String(data[0].id));
            }
        };
        void boot();
    }, []);

    useEffect(() => {
        if (!selectedMerchantId) return;
        void fetchDashboard(selectedMerchantId);
        const timer = setInterval(() => void fetchDashboard(selectedMerchantId), 4000);
        return () => clearInterval(timer);
    }, [selectedMerchantId]);

    const submitPayout = async (e: FormEvent) => {
        e.preventDefault();
        setError("");
        if (!selectedMerchantId) return;

        const response = await fetch(`${API_BASE}/payouts`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": crypto.randomUUID(),
            },
            body: JSON.stringify({
                merchant_id: selectedMerchantId,
                amount_paise: Number(amount),
                bank_account_id: Number(bankId),
            }),
        });
        if (!response.ok) {
            const err = await response.json();
            setError(err.detail ?? "Payout failed");
            return;
        }
        await fetchDashboard(selectedMerchantId);
    };

    return (
        <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
            <div className="mx-auto max-w-6xl space-y-6">
                <h1 className="text-3xl font-semibold">Playto Payout Engine Dashboard</h1>
                <div className="flex gap-3 items-center">
                    <label className="text-sm">Merchant:</label>
                    <select
                        className="bg-slate-900 border border-slate-700 rounded px-3 py-2"
                        value={selectedMerchantId ?? ""}
                        onChange={(e) => setSelectedMerchantId(Number(e.target.value))}
                    >
                        {merchantOptions.map((m) => (
                            <option key={m.value} value={m.value}>
                                {m.label}
                            </option>
                        ))}
                    </select>
                </div>

                {dashboard && (
                    <>
                        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <article className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                                <p className="text-slate-400">Available balance</p>
                                <p className="text-2xl font-bold">{inr(dashboard.available_balance_paise)}</p>
                            </article>
                            <article className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                                <p className="text-slate-400">Held balance</p>
                                <p className="text-2xl font-bold">{inr(dashboard.held_balance_paise)}</p>
                            </article>
                        </section>

                        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                            <h2 className="text-xl mb-3">Request Payout</h2>
                            <form className="flex flex-wrap gap-3 items-end" onSubmit={submitPayout}>
                                <div>
                                    <label className="block text-sm mb-1">Amount (paise)</label>
                                    <input
                                        className="bg-slate-950 border border-slate-700 rounded px-3 py-2"
                                        value={amount}
                                        onChange={(e) => setAmount(e.target.value)}
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm mb-1">Bank Account ID</label>
                                    <input
                                        className="bg-slate-950 border border-slate-700 rounded px-3 py-2"
                                        value={bankId}
                                        onChange={(e) => setBankId(e.target.value)}
                                    />
                                </div>
                                <button className="bg-indigo-600 hover:bg-indigo-500 rounded px-4 py-2" type="submit">
                                    Request
                                </button>
                            </form>
                            {error && <p className="text-rose-400 mt-2">{error}</p>}
                        </section>

                        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 overflow-x-auto">
                            <h2 className="text-xl mb-3">Payout history</h2>
                            <table className="w-full text-left text-sm">
                                <thead>
                                    <tr className="text-slate-400">
                                        <th className="py-2">Payout ID</th>
                                        <th>Amount</th>
                                        <th>Status</th>
                                        <th>Attempts</th>
                                        <th>Reason</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {dashboard.payouts.map((p) => (
                                        <tr key={p.id} className="border-t border-slate-800">
                                            <td className="py-2">{p.id.slice(0, 8)}</td>
                                            <td>{inr(p.amount_paise)}</td>
                                            <td>{p.status}</td>
                                            <td>{p.attempts}</td>
                                            <td>{p.failure_reason || "-"}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </section>

                        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 overflow-x-auto">
                            <h2 className="text-xl mb-3">Recent ledger entries</h2>
                            <table className="w-full text-left text-sm">
                                <thead>
                                    <tr className="text-slate-400">
                                        <th className="py-2">Type</th>
                                        <th>Amount</th>
                                        <th>Time</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {dashboard.recent_ledger.map((entry) => (
                                        <tr key={entry.id} className="border-t border-slate-800">
                                            <td className="py-2">{entry.entry_type}</td>
                                            <td>{inr(entry.amount_paise)}</td>
                                            <td>{new Date(entry.created_at).toLocaleString()}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </section>
                    </>
                )}
            </div>
        </main>
    );
}
