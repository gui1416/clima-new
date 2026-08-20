import { Drawer as DrawerPrimitive } from "@base-ui/react/drawer";
import type { ComponentProps, ReactNode } from "react";

export const Drawer = DrawerPrimitive.Root;
export const DrawerClose = DrawerPrimitive.Close;
export const DrawerTitle = DrawerPrimitive.Title;
export const DrawerDescription = DrawerPrimitive.Description;

export function DrawerContent({ children, className = "", ...props }: ComponentProps<typeof DrawerPrimitive.Popup>) {
  return (
    <DrawerPrimitive.Portal>
      <DrawerPrimitive.Backdrop className="drawer-overlay" />
      <DrawerPrimitive.Viewport className="drawer-viewport">
        <DrawerPrimitive.Popup className={`drawer-content ${className}`.trim()} {...props}>
          {children}
        </DrawerPrimitive.Popup>
      </DrawerPrimitive.Viewport>
    </DrawerPrimitive.Portal>
  );
}

export function DrawerHeader({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <header className={`drawer-header ${className}`.trim()}>{children}</header>;
}
