import { useMutation } from '@tanstack/react-query'
import { postBlink, postPin } from '../lib/api'

// Traditional request/response for LED control (POST /blink).
// Live LED state comes back over the WebSocket, so there's nothing to cache
// here — the Pico broadcasts the new state to /ws/health on success.
export function useLedCommand(host) {
  return useMutation({
    mutationFn: (command) => postBlink(host, command),
  })
}

// GPIO output control (POST /pin). Like the LED, live pin state is echoed back
// over the WebSocket, so we just fire the command.
export function usePinCommand(host) {
  return useMutation({
    mutationFn: (command) => postPin(host, command),
  })
}
