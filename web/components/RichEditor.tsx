"use client";
import { useEditor, EditorContent, Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import { useEffect, forwardRef, useImperativeHandle } from "react";

type Props = {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
};

export type RichEditorHandle = {
  insert: (html: string) => void;
  focus: () => void;
};

function ToolbarBtn({
  onClick,
  active,
  title,
  children,
  disabled,
}: {
  onClick: () => void;
  active?: boolean;
  title: string;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`mh-editor-button px-2.5 py-1 text-[13px] rounded-lg transition-colors ${
        active ? "is-active" : ""
      } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
    >
      {children}
    </button>
  );
}

function Toolbar({ editor }: { editor: Editor }) {
  const addLink = () => {
    const prev = editor.getAttributes("link").href as string | undefined;
    const url = window.prompt("链接 URL", prev || "https://");
    if (url === null) return;
    if (url === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  };
  const addImage = () => {
    const url = window.prompt("图片 URL", "https://");
    if (!url) return;
    editor.chain().focus().setImage({ src: url }).run();
  };
  return (
    <div className="mh-editor-toolbar flex flex-wrap gap-0.5 p-2 rounded-t-xl">
      <ToolbarBtn
        title="粗体"
        active={editor.isActive("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <b>B</b>
      </ToolbarBtn>
      <ToolbarBtn
        title="斜体"
        active={editor.isActive("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        <i>I</i>
      </ToolbarBtn>
      <ToolbarBtn
        title="删除线"
        active={editor.isActive("strike")}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      >
        <s>S</s>
      </ToolbarBtn>
      <span className="w-px bg-neutral-200 mx-1 my-1" />
      <ToolbarBtn
        title="H2 标题"
        active={editor.isActive("heading", { level: 2 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
      >
        H2
      </ToolbarBtn>
      <ToolbarBtn
        title="H3 标题"
        active={editor.isActive("heading", { level: 3 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
      >
        H3
      </ToolbarBtn>
      <span className="w-px bg-neutral-200 mx-1 my-1" />
      <ToolbarBtn
        title="项目列表"
        active={editor.isActive("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        • 列表
      </ToolbarBtn>
      <ToolbarBtn
        title="编号列表"
        active={editor.isActive("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        1. 列表
      </ToolbarBtn>
      <ToolbarBtn
        title="引用"
        active={editor.isActive("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      >
        ❝
      </ToolbarBtn>
      <span className="w-px bg-neutral-200 mx-1 my-1" />
      <ToolbarBtn title="插入链接" active={editor.isActive("link")} onClick={addLink}>
        🔗
      </ToolbarBtn>
      <ToolbarBtn title="插入图片" onClick={addImage}>
        🖼
      </ToolbarBtn>
      <span className="w-px bg-neutral-200 mx-1 my-1" />
      <ToolbarBtn
        title="清除格式"
        onClick={() =>
          editor.chain().focus().clearNodes().unsetAllMarks().run()
        }
      >
        ✕格式
      </ToolbarBtn>
    </div>
  );
}

const RichEditor = forwardRef<RichEditorHandle, Props>(function RichEditor(
  { value, onChange, placeholder },
  ref,
) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({}),
      Link.configure({
        openOnClick: false,
        autolink: true,
        HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" },
      }),
      Image.configure({ inline: false, allowBase64: true }),
    ],
    content: value || "",
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none focus:outline-none min-h-[180px] px-4 py-3 text-[14px] leading-relaxed",
        "data-placeholder": placeholder || "",
      },
    },
    onUpdate: ({ editor }: { editor: Editor }) => {
      const html = editor.getHTML();
      // tiptap returns "<p></p>" for empty; normalize
      onChange(html === "<p></p>" ? "" : html);
    },
  });

  // Expose imperative API so parents can append content without remounting
  useImperativeHandle(ref, () => ({
    insert: (html: string) => {
      if (!editor) return;
      editor.chain().focus("end").insertContent(html).run();
    },
    focus: () => editor?.chain().focus().run(),
  }), [editor]);

  // Sync external value (e.g. clear after send, draft hydration)
  useEffect(() => {
    if (!editor) return;
    const current = editor.getHTML();
    const incoming = value || "";
    const norm = (s: string) => (s === "<p></p>" ? "" : s);
    if (norm(current) !== norm(incoming)) {
      editor.commands.setContent(incoming || "", { emitUpdate: false });
    }
  }, [value, editor]);

  if (!editor) {
    return (
      <div className="mh-editor-skeleton w-full text-sm rounded-xl mt-2 min-h-[220px]" />
    );
  }

  return (
    <div className="mh-editor w-full text-sm rounded-xl mt-2">
      <Toolbar editor={editor} />
      <EditorContent editor={editor} />
    </div>
  );
});

export default RichEditor;
