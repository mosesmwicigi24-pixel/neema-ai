import React from "react";

interface InputFieldProps {
    label: string;
    value: string | number;
    onChange: (v: string) => void;
    type?: React.HTMLInputTypeAttribute;
    placeholder?: string;
    hint?: string;
    required?: boolean;
}

export function InputField({
    label,
    value,
    onChange,
    type = "text",
    placeholder,
    hint,
    required,
}: InputFieldProps): React.ReactElement {
    return (
        <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                {label}
                {required && <span className="text-red-500 ml-0.5">*</span>}
            </label>
            <input
                type={type}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                required={required}
                className="w-full h-10 px-3 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent transition-all"
                style={{ fontSize: 16 }}
            />
            {hint && (
                <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
                    {hint}
                </p>
            )}
        </div>
    );
}

interface SelectFieldProps {
    label: string;
    value: string;
    onChange: (v: string) => void;
    children?: React.ReactNode;
    options?: { value: string; label: string }[];
    hint?: string;
}

export function SelectField({
    label,
    value,
    onChange,
    children,
    options,
    hint,
}: SelectFieldProps): React.ReactElement {
    return (
        <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                {label}
            </label>
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="w-full h-10 px-3 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent transition-all cursor-pointer"
                style={{ fontSize: 16 }}
            >
                {options
                    ? options.map((o) => (
                          <option key={o.value} value={o.value}>
                              {o.label}
                          </option>
                      ))
                    : children}
            </select>
            {hint && (
                <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
                    {hint}
                </p>
            )}
        </div>
    );
}

interface TextareaFieldProps {
    label?: string;
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
    rows?: number;
    disabled?: boolean;
    onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
    className?: string;
}

export function TextareaField({
    label,
    value,
    onChange,
    placeholder,
    rows = 3,
    disabled,
    onKeyDown,
    className = "",
}: TextareaFieldProps): React.ReactElement {
    return (
        <div className="mb-4">
            {label && (
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                    {label}
                </label>
            )}
            <textarea
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                rows={rows}
                disabled={disabled}
                onKeyDown={onKeyDown}
                className={`w-full px-3 py-2.5 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent resize-none transition-all disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
                style={{ fontSize: 16 }}
            />
        </div>
    );
}