import { Chat } from "./components/Chat";
import { AurixMessenger, MessengerContext } from "./context/AurixMessenger";

const messenger = new AurixMessenger();

export default function App() {
  return (
    <MessengerContext.Provider value={messenger}>
      <div className="flex flex-col h-full">
        <Chat />
      </div>
    </MessengerContext.Provider>
  );
}
