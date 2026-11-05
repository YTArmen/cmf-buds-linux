export type SppStateEvent = { address: string; connected: boolean; error?: string };
export type SppDataEvent = { address: string; hex: string };
export type AppleAdvEvent = { address: string; hex: string; rssi: number };

export type BudsBtModuleEvents = {
  onSppState: (e: SppStateEvent) => void;
  onSppData: (e: SppDataEvent) => void;
  onAppleAdv: (e: AppleAdvEvent) => void;
};

export type BondedDevice = { address: string; name: string };
