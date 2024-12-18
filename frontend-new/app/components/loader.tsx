import { cn } from "~/lib/utils";

type LoaderProps = { className?: string };
export function Loader({ className }: LoaderProps) {
  return (
    <div className={cn("flex h-screen items-center justify-center", className)}>
      <svg
        className="loader-svg w-52"
        data-name="Layer 1"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 820.25 778.36"
      >
        <path d="M739.11,389.19c0,37.87-12.19,72.88-32.85,101.33-17.63,24.33-41.47,43.84-69.18,56.25-21.47,9.62-45.26,14.97-70.3,14.97H81.15v-70.46l.76-.76,202.22-202.22H81.15v-71.21s304.44,0,304.44,0v70.46l-.76.76-202.21,202.22h119.02s276.65.01,276.65.01c.01-.01.04-.01.05-.01,50.83-5.73,90.31-48.92,90.31-101.33,0-56.34-45.6-102.01-101.87-102.01s-101.87,45.68-101.87,102.01c0,3.46.17,6.88.51,10.24l-57.08,57.69c-8.94-20.85-13.89-43.81-13.89-67.94,0-95.3,77.16-172.56,172.33-172.56s172.33,77.26,172.33,172.56Z" />
      </svg>
    </div>
  );
}
