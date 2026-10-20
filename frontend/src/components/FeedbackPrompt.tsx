import { useState } from "react";
import { useSession } from "../state/SessionStore";

export function FeedbackPrompt({ episodeId }: { episodeId: string }) {
  const { submitFeedback } = useSession();
  const [answered, setAnswered] = useState(false);

  if (answered) return <div className="text-[12px] text-[#5B6275] dark:text-[#9198A8]">Thanks for the feedback.</div>;

  const answer = (worked: boolean) => {
    setAnswered(true);
    void submitFeedback(episodeId, worked);
  };
  const btn = "rounded-lg border border-[#9198A8]/40 px-2.5 py-0.5 text-[12px] hover:bg-[#9198A8]/10";
  return (
    <div className="flex items-center gap-2 text-[12px] text-[#5B6275] dark:text-[#9198A8]">
      Did this fix it?
      <button type="button" className={btn} onClick={() => answer(true)}>Yes</button>
      <button type="button" className={btn} onClick={() => answer(false)}>No</button>
    </div>
  );
}
