namespace Ryujinx.Graphics.Shader.Translation
{
    public readonly struct TranslationOptions
    {
        public TargetLanguage TargetLanguage { get; }
        public TargetApi TargetApi { get; }
        public TranslationFlags Flags { get; }
        // nxnative: the most times one entry into a loop runs its body (SPIR-V only, 0 = no limit). A loop whose bound comes from memory that holds garbage would otherwise
        // hang the GPU (Ocarina of Time's light-list loops in Kokiri); with the cap it exits early and at worst shades a pixel wrong (SpirvGenerator, DMSH_LOOP_CAP)
        public uint LoopIterationCap { get; }

        public TranslationOptions(TargetLanguage targetLanguage, TargetApi targetApi, TranslationFlags flags, uint loopIterationCap = 0)
        {
            TargetLanguage = targetLanguage;
            TargetApi = targetApi;
            Flags = flags;
            LoopIterationCap = loopIterationCap;
        }
    }
}
