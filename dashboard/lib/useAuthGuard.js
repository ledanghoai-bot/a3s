"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "./api";

// Dung o dau moi trang can dang nhap: neu chua co token thi day ve /login,
// tra ve `ready = true` khi da xac nhan co token de trang bat dau goi API.
export function useAuthGuard() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  return ready;
}
