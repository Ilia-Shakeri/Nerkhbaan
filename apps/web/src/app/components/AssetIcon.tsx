import gold from '../../assets/crypto/gold.svg';
import silver from '../../assets/crypto/silver.svg';
import btc from '../../assets/crypto/btc.svg';
import usdt from '../../assets/crypto/usdt.svg';
const icons: Record<string, string> = { gold, silver, btc, bitcoin: btc, usdt, tether: usdt };
export function AssetIcon({ id, className = '' }: { id: string; className?: string }) {
  if (!icons[id]) return <svg viewBox="0 0 32 32" fill="none" stroke="#B68A29" strokeWidth="1.8" aria-hidden="true" className={`asset-icon ${className}`}><path d="M5 24h22M7 20l6-7 6 3 6-9" /></svg>;
  return <img src={icons[id]} width={40} height={40} alt="" aria-hidden="true" className={`asset-icon ${className}`} />;
}
