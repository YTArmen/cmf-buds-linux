import { NativeModule, requireNativeModule } from 'expo';

import { BondedDevice, BudsBtModuleEvents } from './BudsBt.types';

declare class BudsBtModule extends NativeModule<BudsBtModuleEvents> {
  isEnabled(): boolean;
  bondedDevices(): BondedDevice[];
  connectSpp(address: string, uuid: string, channel: number): Promise<void>;
  isSppConnected(address: string): boolean;
  disconnectSpp(address: string): void;
  writeSpp(address: string, hex: string): boolean;
  startAppleScan(): boolean;
  stopAppleScan(): void;
}

export default requireNativeModule<BudsBtModule>('BudsBt');
export * from './BudsBt.types';
