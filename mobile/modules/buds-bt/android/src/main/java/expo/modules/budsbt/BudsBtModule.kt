package expo.modules.budsbt

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * Bluetooth для наушников:
 *  - SPP/RFCOMM (CMF Buds и другие Nothing): подключение, отправка и приём байтов;
 *  - BLE-рассылка Apple (AirPods): заряд и «в ушах», без подключения.
 * Разбор протоколов — в TypeScript, здесь только транспорт.
 */
@SuppressLint("MissingPermission")
class BudsBtModule : Module() {
  private val sockets = ConcurrentHashMap<String, BluetoothSocket>()
  private var scanCallback: ScanCallback? = null

  private val adapter: BluetoothAdapter?
    get() {
      val ctx = appContext.reactContext ?: return null
      return (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
    }

  override fun definition() = ModuleDefinition {
    Name("BudsBt")

    Events("onSppState", "onSppData", "onAppleAdv")

    Function("isEnabled") { adapter?.isEnabled == true }

    Function("bondedDevices") {
      adapter?.bondedDevices?.map { mapOf("address" to it.address, "name" to (it.name ?: "")) }
        ?: emptyList()
    }

    AsyncFunction("connectSpp") { address: String, uuid: String, channel: Int ->
      val dev = adapter?.getRemoteDevice(address) ?: throw Exception("Bluetooth выключен")
      Thread { runSpp(dev, uuid, channel) }.start()
    }

    Function("disconnectSpp") { address: String ->
      sockets.remove(address)?.let { runCatching { it.close() } }
    }

    Function("writeSpp") { address: String, hex: String ->
      val s = sockets[address] ?: return@Function false
      runCatching { s.outputStream.write(hexToBytes(hex)); s.outputStream.flush() }.isSuccess
    }

    Function("startAppleScan") {
      val scanner = adapter?.bluetoothLeScanner ?: return@Function false
      if (scanCallback != null) return@Function true
      // 0x07 0x19 — сообщение Apple «proximity pairing» от AirPods/Beats
      val filter = ScanFilter.Builder()
        .setManufacturerData(0x004C, byteArrayOf(0x07, 0x19), byteArrayOf(-1, -1))
        .build()
      val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
      val cb = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
          val data = result.scanRecord?.getManufacturerSpecificData(0x004C) ?: return
          sendEvent("onAppleAdv", mapOf(
            "hex" to bytesToHex(data), "rssi" to result.rssi, "address" to result.device.address))
        }
      }
      scanCallback = cb
      runCatching { scanner.startScan(listOf(filter), settings, cb) }.isSuccess
    }

    Function("stopAppleScan") {
      scanCallback?.let { cb -> runCatching { adapter?.bluetoothLeScanner?.stopScan(cb) } }
      scanCallback = null
    }

    OnDestroy {
      sockets.values.forEach { runCatching { it.close() } }
      sockets.clear()
      scanCallback?.let { cb -> runCatching { adapter?.bluetoothLeScanner?.stopScan(cb) } }
    }
  }

  private fun openSocket(dev: BluetoothDevice, uuid: String, channel: Int): BluetoothSocket {
    adapter?.cancelDiscovery()
    // 1) по UUID службы; 2) запасной путь — прямо номер канала (скрытый метод Android)
    if (uuid.isNotEmpty()) {
      try {
        val s = dev.createRfcommSocketToServiceRecord(UUID.fromString(uuid))
        s.connect()
        return s
      } catch (_: Exception) {
      }
    }
    val m = dev.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
    val s = m.invoke(dev, channel) as BluetoothSocket
    s.connect()
    return s
  }

  private fun runSpp(dev: BluetoothDevice, uuid: String, channel: Int) {
    val address = dev.address
    sockets.remove(address)?.let { runCatching { it.close() } }
    val s = try {
      openSocket(dev, uuid, channel)
    } catch (e: Exception) {
      sendEvent("onSppState", mapOf("address" to address, "connected" to false,
        "error" to (e.message ?: e.javaClass.simpleName)))
      return
    }
    sockets[address] = s
    sendEvent("onSppState", mapOf("address" to address, "connected" to true))
    val buf = ByteArray(1024)
    try {
      val input = s.inputStream
      while (true) {
        val n = input.read(buf)
        if (n < 0) break
        if (n > 0) sendEvent("onSppData", mapOf("address" to address, "hex" to bytesToHex(buf.copyOf(n))))
      }
    } catch (_: Exception) {
    }
    if (sockets[address] === s) sockets.remove(address)
    runCatching { s.close() }
    sendEvent("onSppState", mapOf("address" to address, "connected" to false))
  }

  private fun bytesToHex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }

  private fun hexToBytes(h: String) = ByteArray(h.length / 2) { h.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
}
